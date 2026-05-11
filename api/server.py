"""
FastAPI server — the backend that the Streamlit UI talks to.

Endpoints
─────────
POST /api/scrape          Start a new scraping task (runs in background)
GET  /api/tasks/{id}      Poll for task status, logs, and results
GET  /api/session/status  Check if a browser session exists
GET  /api/health          Simple health-check

Architecture
────────────
Scraping runs in a background thread so the API stays responsive.
Results are stored in an in-memory dict keyed by ``task_id``.
This is intentionally simple — no database, no Redis, no Celery.
"""

from __future__ import annotations

import os
import uuid
import time as _time
import threading
import csv
import json
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import ScrapeRequest, TaskStatus
from .scraper import InstagramScraper
from .utils import normalize_url, extract_username

# ──────────────────────────────────────────────
# App & config
# ──────────────────────────────────────────────

app = FastAPI(
    title="Instagram Scraper Pro API",
    version="2.0.0",
    description="Camoufox-powered Instagram scraper with Apify-level data extraction.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_DIR = os.path.join(os.getcwd(), "ig_session")

# In-memory task store:  task_id → TaskStatus dict
tasks: dict[str, dict] = {}


# ──────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ──────────────────────────────────────────────
# Session status
# ──────────────────────────────────────────────

@app.get("/api/session/status")
def session_status():
    """Check whether a persistent browser session already exists."""
    exists = os.path.isdir(SESSION_DIR) and len(os.listdir(SESSION_DIR)) > 5
    return {"session_exists": exists, "session_dir": SESSION_DIR}


# ──────────────────────────────────────────────
# Start a scraping task
# ──────────────────────────────────────────────

@app.post("/api/scrape", response_model=TaskStatus)
def start_scrape(req: ScrapeRequest):
    """
    Kick off a background scraping task.  Returns a ``task_id`` that
    the frontend can poll via ``GET /api/tasks/{task_id}``.
    """
    task_id = uuid.uuid4().hex[:8]

    # Normalise URLs
    urls = [normalize_url(u) for u in req.urls if normalize_url(u)]
    if not urls:
        raise HTTPException(400, "No valid URLs provided.")

    # Initialise task record
    tasks[task_id] = {
        "task_id": task_id,
        "status": "running",
        "progress": 0.0,
        "current_label": "Initializing…",
        "logs": [],
        "error": None,
        "profiles": [],
        "media": [],
        "duration_minutes": 0.0,
    }

    # Run in background thread
    t = threading.Thread(
        target=_run_task,
        args=(task_id, urls, req.media_limit, req.media_skip, req.headless, req.anonymous, req.proxy),
        daemon=True,
    )
    t.start()

    return TaskStatus(**tasks[task_id])


# ──────────────────────────────────────────────
# Poll task status
# ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}", response_model=TaskStatus)
def get_task(task_id: str):
    """Return current status, logs, and (when done) results for a task."""
    if task_id not in tasks:
        raise HTTPException(404, f"Task {task_id} not found.")
    return TaskStatus(**tasks[task_id])


# ──────────────────────────────────────────────
# List all tasks
# ──────────────────────────────────────────────

@app.get("/api/tasks")
def list_tasks():
    """List all task IDs and their statuses."""
    return [
        {"task_id": tid, "status": t["status"]}
        for tid, t in tasks.items()
    ]


# ──────────────────────────────────────────────
# Synchronous Direct Endpoints (for Frontend clients)
# ──────────────────────────────────────────────

@app.get("/api/scrape/profile")
def scrape_profile_sync(url: str, headless: bool = True):
    """
    Synchronous endpoint to instantly scrape a profile.
    Ideal for direct frontend REST calls.
    """
    url = normalize_url(url)
    if not url:
        raise HTTPException(400, "Invalid URL provided.")
    
    scraper = InstagramScraper(session_dir=SESSION_DIR, headless=headless)
    try:
        scraper.start()
        profile_data = scraper.scrape_profile(url)
        return {"status": "success", "data": profile_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        scraper.stop()


@app.get("/api/scrape/media")
def scrape_media_sync(url: str, limit: int = 12, skip: int = 0, headless: bool = True):
    """
    Synchronous endpoint to instantly scrape media from a profile.
    limit: How many media posts to extract.
    skip: How many posts to skip before starting.
    """
    url = normalize_url(url)
    if not url:
        raise HTTPException(400, "Invalid URL provided.")
        
    scraper = InstagramScraper(session_dir=SESSION_DIR, headless=headless)
    username = extract_username(url)
    try:
        scraper.start()
        media_data = scraper.scrape_media(url, limit=limit, username=username, skip=skip)
        return {"status": "success", "data": media_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        scraper.stop()



# ──────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────

def _parse_proxy(proxy_str: str | None) -> dict | None:
    """Parse a proxy URL string into the dict format Camoufox/Playwright expects."""
    if not proxy_str or not proxy_str.strip():
        return None
    from urllib.parse import urlparse
    p = urlparse(proxy_str.strip())
    result = {"server": f"{p.scheme}://{p.hostname}"}
    if p.port:
        result["server"] += f":{p.port}"
    if p.username:
        result["username"] = p.username
    if p.password:
        result["password"] = p.password
    return result


def _run_task(
    task_id: str,
    urls: list[str],
    media_limit: int,
    media_skip: int,
    headless: bool,
    anonymous: bool = False,
    proxy_str: str | None = None,
):
    """
    The actual scraping logic — runs in its own thread.
    Updates ``tasks[task_id]`` in place so the polling endpoint
    always returns fresh data.
    """
    task = tasks[task_id]
    start = _time.time()
    _seen_shortcodes = set()  # dedup tracker

    def log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        task["logs"].append(f"[{ts}] {msg}")

    def progress(current, total, label):
        task["progress"] = current / total if total else 0
        task["current_label"] = label
        # Fix #1: update elapsed time in real-time
        task["duration_minutes"] = round((_time.time() - start) / 60, 2)

    proxy = _parse_proxy(proxy_str)

    scraper = InstagramScraper(
        session_dir=SESSION_DIR,
        headless=headless,
        on_log=log,
        on_progress=progress,
        anonymous=anonymous,
        proxy=proxy,
    )

    OUTPUT_ROOT = os.path.join(os.getcwd(), "output")

    try:
        scraper.start()
        _time.sleep(2)  # Safety buffer

        for idx, url in enumerate(urls):
            username = extract_username(url)
            account_label = f"@{username} ({idx + 1}/{len(urls)})"
            task["current_label"] = f"Scraping {account_label}…"
            task["progress"] = idx / len(urls)

            log(f"━━━ {account_label} ━━━")

            # 1. Profile
            try:
                profile = scraper.scrape_profile(url)
                task["profiles"].append(profile)
            except Exception as e:
                log(f"❌ Profile error for {account_label}: {e}")
                profile = {"username": username}
                task["profiles"].append(profile)

            # 2. Media (posts & reels) — with incremental saving & dedup
            try:
                if media_limit != -1:
                    def _on_media_item(item):
                        """Called after each media item — dedup + incremental save."""
                        sc = item.get("short_code", "")
                        if sc in _seen_shortcodes:
                            return  # duplicate — skip
                        _seen_shortcodes.add(sc)
                        task["media"].append(item)
                        # Update elapsed time
                        task["duration_minutes"] = round((_time.time() - start) / 60, 2)
                        # Save partial CSV every 25 items
                        count = len(task["media"])
                        if count % 25 == 0:
                            try:
                                uname = item.get("owner_username", username)
                                csv_dir = Path(OUTPUT_ROOT) / uname / "csv"
                                csv_dir.mkdir(parents=True, exist_ok=True)
                                partial_path = csv_dir / f"{uname}_partial.csv"
                                user_media = [m for m in task["media"] if m.get("owner_username") == uname]
                                if user_media:
                                    keys = list(user_media[0].keys())
                                    with open(partial_path, "w", newline="", encoding="utf-8") as f:
                                        w = csv.DictWriter(f, fieldnames=keys)
                                        w.writeheader()
                                        w.writerows(user_media)
                                log(f"💾 Incremental save: {count} items → {partial_path}")
                            except Exception as e:
                                log(f"⚠️ Incremental save error: {e}")

                    scraper.scrape_media(
                        url, limit=media_limit, username=username,
                        skip=media_skip, on_media_item=_on_media_item
                    )
                    # Items already added via callback — no extend needed
            except Exception as e:
                log(f"❌ Media error for {account_label}: {e}")

            # Human-like pause between accounts
            if idx < len(urls) - 1:
                delay = random_delay_between_accounts(idx)
                log(f"⏳ Waiting {delay}s before next account…")
                _time.sleep(delay)

        task["status"] = "completed"
        task["progress"] = 1.0
        task["current_label"] = "Saving CSV…"

        # ── Save final CSV outputs per username ──
        for prof in task["profiles"]:
            uname = prof.get("username", "unknown")
            user_media = [m for m in task["media"] if m.get("owner_username") == uname]

            try:
                csv_dir = Path(OUTPUT_ROOT) / uname / "csv"
                csv_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path = csv_dir / f"{uname}_{ts}.csv"
                if user_media:
                    keys = list(user_media[0].keys())
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        w = csv.DictWriter(f, fieldnames=keys)
                        w.writeheader()
                        w.writerows(user_media)
                else:
                    # Profile-only CSV
                    keys = list(prof.keys())
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        w = csv.DictWriter(f, fieldnames=keys)
                        w.writeheader()
                        w.writerow(prof)
                log(f"📄 CSV saved: {csv_path}")
            except Exception as e:
                log(f"⚠️ CSV save error for @{uname}: {e}")

        task["current_label"] = "Done!"
        dur = round((_time.time() - start) / 60, 2)
        log(f"🎉 All done in {dur}m — {len(task['profiles'])} profiles, {len(task['media'])} media items.")

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        log(f"💥 Fatal error: {e}")

    finally:
        try:
            scraper.stop()
        except Exception:
            pass
        task["duration_minutes"] = round((_time.time() - start) / 60, 2)


def random_delay_between_accounts(idx: int) -> int:
    """Increasing delay between accounts to look more human."""
    import random
    base = 2
    return base + random.randint(0, 2) + (idx * 1)
