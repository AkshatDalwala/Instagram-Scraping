"""
Instagram Scraper Engine — powered by Camoufox (anti-detect browser).

This is the heart of the project.  It opens a stealthy Firefox instance,
navigates Instagram like a real person, and extracts every data point
that Apify-style scrapers provide.

Key features
────────────
• Anti-detect fingerprinting via Camoufox
• Persistent session (login survives restarts)
• Human-like delays + cursor humanization
• Profile, post/reel, comments, and hashtag scraping
• Callback hooks for real-time progress in the UI
"""

from __future__ import annotations

import os
import re
import random
import time as _time
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from camoufox.sync_api import Camoufox

from .utils import (
    parse_count,
    extract_username,
    extract_shortcode,
    extract_hashtags,
    extract_mentions,
    extract_keywords,
    format_number,
)


class InstagramScraper:
    """
    Camoufox-based Instagram scraper.

    Usage::

        scraper = InstagramScraper(on_log=print)
        scraper.start()
        profile = scraper.scrape_profile("https://www.instagram.com/natgeo/")
        media   = scraper.scrape_media("https://www.instagram.com/natgeo/", limit=10)
        scraper.stop()

    Parameters
    ----------
    session_dir : str
        Directory for browser profile persistence (cookies, login state).
    headless : bool
        ``True`` to hide the browser window (set ``False`` for first-time login).
    on_log : callable
        ``fn(message: str)`` — called for every log line.
    on_progress : callable
        ``fn(current: int, total: int, label: str)`` — progress updates.
    """

    def __init__(
        self,
        session_dir: str | None = None,
        headless: bool = False,
        on_log=None,
        on_progress=None,
        anonymous: bool = False,
        proxy: dict | None = None,
    ):
        self.session_dir = session_dir or os.path.join(os.getcwd(), "ig_session")
        self.headless = headless
        self.log = on_log or (lambda msg: print(msg))
        self.progress = on_progress or (lambda *a, **kw: None)
        self.anonymous = anonymous
        self.proxy = proxy            # {"server": "...", "username": "...", "password": "..."}

        # Managed by start() / stop()
        self._camoufox_cm = None   # context-manager object
        self._context = None       # BrowserContext
        self._page = None          # active Page
        self._media_cache = {}     # shortcode -> {likes, comments, views}
        self._temp_dir = None      # throwaway profile dir for anonymous mode

    # ══════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ══════════════════════════════════════════════════════════════

    def start(self):
        """Launch Camoufox with anti-detect settings."""
        mode_label = "anonymous (no login)" if self.anonymous else "persistent session"
        self.log(f"🦊 Launching Camoufox — {mode_label}…")

        # Determine profile directory
        if self.anonymous:
            import tempfile
            self._temp_dir = tempfile.mkdtemp(prefix="ig_anon_")
            user_data_dir = self._temp_dir
            self.log("🔓 Anonymous mode: using fresh browser profile (no cookies).")
        else:
            user_data_dir = self.session_dir

        # Build Camoufox kwargs
        cm_kwargs = dict(
            persistent_context=True,
            user_data_dir=user_data_dir,
            headless=self.headless,
            humanize=True,           # Human-like cursor movements
            os="windows",            # Match the host OS for fingerprint
            enable_cache=True,       # Allow back/forward navigation
            viewport={"width": 1024, "height": 768},
        )
        if self.proxy:
            cm_kwargs["proxy"] = self.proxy
            self.log(f"🌐 Proxy configured: {self.proxy.get('server', '?')}")

        try:
            self._camoufox_cm = Camoufox(**cm_kwargs)
            # Manually enter the context manager so we control when it closes
            self._context = self._camoufox_cm.__enter__()
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )
            
            # Attach background listener for API data "sniffing"
            self._setup_network_listener()
            
            # ── Stability Wait ──
            # Give the browser 5 seconds to settle its fingerprints
            self.log("⏳ Stabilizing browser engine...")
            _time.sleep(5)
            
            self.log("✅ Browser ready.")
        except Exception as e:
            self.log(f"❌ Browser failed to start: {e}")
            raise e

    def _setup_network_listener(self):
        """Monitor background traffic for raw API metrics."""
        def handle_response(response):
            try:
                url = response.url
                # Target: Instagram API v1 info or GraphQL media queries
                if ("/api/v1/media/" in url and "/info/" in url) or ("/graphql/query" in url):
                    # We only care about successful JSON responses
                    if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                        data = response.json()
                        self._process_api_payload(data)
            except:
                pass
        
        self._page.on("response", handle_response)

    def _process_api_payload(self, data):
        """Recursively extract metrics from any JSON payload found in background traffic."""
        def find_media_nodes(obj):
            if isinstance(obj, dict):
                # Look for objects that look like media entries
                sc = obj.get("shortcode") or obj.get("code")
                if sc:
                    # Likes: Standard, GraphQL, or Alternative
                    l = obj.get("like_count") or (obj.get("edge_media_preview_like") or {}).get("count") or obj.get("fb_like_count")
                    # Comments: Standard or GraphQL
                    c = obj.get("comment_count") or (obj.get("edge_media_to_comment") or {}).get("count")
                    # Views/Plays: Try every known Instagram internal field name
                    v = (
                        obj.get("play_count") or 
                        obj.get("view_count") or 
                        obj.get("video_view_count") or 
                        obj.get("fb_play_count") or
                        obj.get("video_play_count") or
                        (obj.get("video_view_count_info") or {}).get("count")
                    )
                    # Reposts/Shares: Instagram exposes reshare counts in API
                    rp = (
                        obj.get("reshare_count") or
                        obj.get("share_count") or
                        obj.get("repost_count") or
                        (obj.get("edge_media_to_reshare") or {}).get("count")
                    )
                    # Saves: Instagram exposes save counts in API (owner-only on some endpoints)
                    sv = (
                        obj.get("save_count") or
                        obj.get("saved_count") or
                        (obj.get("edge_media_to_save") or {}).get("count")
                    )
                    
                    current = self._media_cache.get(sc, {})
                    update = dict(current)  # preserve existing fields

                    if l is not None: update["likes"] = str(int(l))
                    if c is not None: update["comments"] = str(int(c))
                    if v is not None: update["views"] = str(int(v))
                    if rp is not None: update["reposts"] = str(int(rp))
                    if sv is not None: update["saves"] = str(int(sv))

                    # ── Caption ──
                    if "caption" not in update:
                        cap_obj = obj.get("caption")
                        if isinstance(cap_obj, dict):
                            cap_text = cap_obj.get("text", "")
                        elif isinstance(cap_obj, str):
                            cap_text = cap_obj
                        else:
                            cap_text = ""
                            edge_cap = obj.get("edge_media_to_caption", {})
                            if isinstance(edge_cap, dict):
                                edges = edge_cap.get("edges", [])
                                if edges and isinstance(edges[0], dict):
                                    cap_text = edges[0].get("node", {}).get("text", "")
                        if cap_text:
                            update["caption"] = cap_text

                    # ── Timestamp ──
                    if "timestamp" not in update:
                        ts = obj.get("taken_at") or obj.get("taken_at_timestamp")
                        if ts: update["timestamp"] = str(int(ts))

                    # ── Media type ──
                    if "media_type" not in update:
                        is_video = obj.get("is_video", False)
                        product_type = obj.get("product_type", "")
                        mt_code = obj.get("media_type")  # 1=photo, 2=video, 8=carousel
                        carousel = obj.get("edge_sidecar_to_children") or obj.get("carousel_media")
                        if product_type == "clips":
                            update["media_type"] = "Reel"
                        elif carousel:
                            update["media_type"] = "Carousel"
                            carousel_urls = []
                            if isinstance(carousel, dict):
                                edges = carousel.get("edges", [])
                                update["carousel_count"] = len(edges)
                                for edge in edges:
                                    node = edge.get("node", {}) if isinstance(edge, dict) else {}
                                    # Video child
                                    vu = node.get("video_url")
                                    if not vu:
                                        vv = node.get("video_versions")
                                        if isinstance(vv, list) and vv:
                                            vu = vv[0].get("url")
                                    if vu and not vu.startswith("blob:"):
                                        carousel_urls.append(vu)
                                    else:
                                        # Image child
                                        img = node.get("display_url") or node.get("thumbnail_src")
                                        if not img:
                                            iv = node.get("image_versions2", {}).get("candidates")
                                            if isinstance(iv, list) and iv:
                                                img = iv[0].get("url")
                                        if img:
                                            carousel_urls.append(img)
                            elif isinstance(carousel, list):
                                update["carousel_count"] = len(carousel)
                                for child in carousel:
                                    if not isinstance(child, dict):
                                        continue
                                    # Video child
                                    vu = child.get("video_url")
                                    if not vu:
                                        vv = child.get("video_versions")
                                        if isinstance(vv, list) and vv:
                                            vu = vv[0].get("url")
                                    if vu and not vu.startswith("blob:"):
                                        carousel_urls.append(vu)
                                    else:
                                        # Image child
                                        img = child.get("display_url") or child.get("thumbnail_src")
                                        if not img:
                                            iv = child.get("image_versions2", {}).get("candidates")
                                            if isinstance(iv, list) and iv:
                                                img = iv[0].get("url")
                                        if img:
                                            carousel_urls.append(img)
                            if carousel_urls:
                                update["carousel_urls"] = " | ".join(carousel_urls)
                        elif mt_code == 8:
                            update["media_type"] = "Carousel"
                        elif is_video or mt_code == 2:
                            update["media_type"] = "Video"
                        else:
                            update["media_type"] = "Photo"

                    # ── Owner ──
                    if "owner_username" not in update:
                        owner_obj = obj.get("owner") or obj.get("user")
                        if isinstance(owner_obj, dict):
                            uname = owner_obj.get("username", "")
                            if uname: update["owner_username"] = uname

                    # ── Location ──
                    if "location_id" not in update:
                        loc = obj.get("location")
                        if isinstance(loc, dict):
                            update["location_id"] = str(loc.get("pk", "") or loc.get("id", ""))

                    # ── Tagged users ──
                    if "tagged_users" not in update:
                        tagged = obj.get("edge_media_to_tagged_user") or obj.get("usertags")
                        if isinstance(tagged, dict):
                            tagged_list = tagged.get("in", []) or tagged.get("edges", [])
                            update["tagged_users"] = len(tagged_list)

                    # ── Audio (reels) ──
                    if "audio_title" not in update:
                        music = obj.get("clips_music_attribution_info")
                        if isinstance(music, dict):
                            update["audio_title"] = music.get("song_name", "")
                        if not update.get("audio_title"):
                            mm = obj.get("music_metadata")
                            if isinstance(mm, dict):
                                info = mm.get("music_info", {}).get("music_asset_info", {})
                                if isinstance(info, dict):
                                    update["audio_title"] = info.get("title", "")

                    # ── Sponsored ──
                    if obj.get("is_paid_partnership") or obj.get("is_ad") or obj.get("is_organic_product_tagging_eligible"):
                        update["is_sponsored"] = True

                    # ── Pinned ──
                    if obj.get("timeline_pinned_user_ids"):
                        # This post appears in the pinned list
                        update["is_pinned"] = True

                    # Capture video URL from API response
                    vid_url = obj.get("video_url")
                    if not vid_url:
                        vv = obj.get("video_versions")
                        if isinstance(vv, list) and vv:
                            vid_url = vv[0].get("url")
                    if vid_url and not vid_url.startswith("blob:"):
                        update["video_url"] = vid_url

                    # Capture display/thumbnail URL from API response
                    thumb = obj.get("thumbnail_src") or obj.get("display_url")
                    if not thumb:
                        iv = obj.get("image_versions2", {}).get("candidates")
                        if isinstance(iv, list) and iv:
                            thumb = iv[0].get("url")
                    if not thumb:
                        thumb = (obj.get("thumbnail_resources") or [{}])[-1].get("src")
                    if thumb:
                        update["display_url"] = thumb

                    if update:
                        self._media_cache[sc] = update

                for val in obj.values():
                    find_media_nodes(val)
            elif isinstance(obj, list):
                for item in obj:
                    find_media_nodes(item)
        
        try:
            find_media_nodes(data)
        except:
            pass

    def stop(self):
        """Shut down the browser cleanly."""
        try:
            if self._camoufox_cm:
                self._camoufox_cm.__exit__(None, None, None)
        except Exception:
            pass
        # Clean up throwaway profile for anonymous mode
        if self._temp_dir:
            try:
                import shutil
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
            self._temp_dir = None
        self._page = None
        self._context = None
        self._camoufox_cm = None
        self.log("🛑 Browser closed.")

    # ══════════════════════════════════════════════════════════════
    #  NAVIGATION HELPERS
    # ══════════════════════════════════════════════════════════════

    def _navigate(self, url: str):
        """Go to *url*, detect login walls, and wait like a human."""
        page = self._page
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        self._human_delay(5000, 8000)

        # Check for login / challenge screens
        needs_login = False
        try:
            needs_login = (
                page.locator('input[name="username"]').is_visible()
                or page.locator('text="Log In"').first.is_visible()
                or "login" in page.url.lower()
                or "/challenge/" in page.url.lower()
            )
        except Exception:
            pass

        if needs_login:
            if self.anonymous:
                # Anonymous mode — dismiss the login wall and continue
                self.log("🔓 Login prompt detected — dismissing (anonymous mode)…")
                self._dismiss_login_wall(page, url)
            elif self.headless:
                self.log("❌ LOGIN REQUIRED but running in HEADLESS mode.")
                self.log("   Please run in NON-HEADLESS mode (Toggle in sidebar) once to log in manually.")
                raise Exception("Authentication required. Please disable headless mode and log in.")
            else:
                self.log("⚠️  LOGIN REQUIRED — please log in in the browser window.")
                self.log("   Waiting 120 s for manual resolution…")
                page.wait_for_timeout(120_000)
        else:
            # Dismiss any "Turn on notifications" or cookie banners even on normal pages
            if self.anonymous:
                self._dismiss_login_wall(page, url)
            self._human_delay(3000, 5000)

    def _dismiss_login_wall(self, page, original_url: str):
        """
        Try to dismiss Instagram login popups, overlays, and banners
        without actually logging in.  Used in anonymous mode.
        """
        # 1. If we were redirected to /accounts/login/, go back
        if "/accounts/login" in page.url.lower() or "/challenge/" in page.url.lower():
            self.log("   ↩️ Redirected to login page — navigating back…")
            try:
                page.goto(original_url, timeout=30_000, wait_until="domcontentloaded")
                self._human_delay(3000, 5000)
            except Exception:
                pass

        # 2. Click "Not Now" / "Decline" buttons (notification prompts, cookie banners)
        for label in ["Not Now", "Not now", "Decline", "Cancel", "Close"]:
            try:
                btn = page.locator(f'button:has-text("{label}")').first
                if btn.is_visible(timeout=800):
                    btn.click(timeout=1500)
                    self._human_delay(400, 800)
            except Exception:
                pass

        # 3. Press Escape to close any remaining modals
        try:
            page.keyboard.press("Escape")
            self._human_delay(400, 700)
        except Exception:
            pass

        # 4. Remove login overlays via JS (Instagram renders a blocking <div>)
        try:
            page.evaluate("""
                () => {
                    // Remove modal overlays that contain login prompts
                    document.querySelectorAll('[role="presentation"], [role="dialog"]').forEach(el => {
                        const t = (el.textContent || '').toLowerCase();
                        if (t.includes('log in') || t.includes('sign up') || t.includes('create an account')) {
                            el.remove();
                        }
                    });
                    // Re-enable scrolling (Instagram locks body scroll when overlay is open)
                    document.body.style.overflow = 'auto';
                    document.documentElement.style.overflow = 'auto';
                    // Remove the fixed-position backdrop if any
                    document.querySelectorAll('div[style*="position: fixed"]').forEach(el => {
                        const t = (el.textContent || '').toLowerCase();
                        if (t.includes('log in') || t.includes('sign up')) {
                            el.remove();
                        }
                    });
                }
            """)
        except Exception:
            pass

        # 5. Final Escape in case JS removal triggered new focus
        try:
            page.keyboard.press("Escape")
            self._human_delay(300, 500)
        except Exception:
            pass

    def _human_delay(self, lo: int = 1500, hi: int = 3000):
        # Speed up significantly by dividing the requested delay by 4 (slightly slower to ensure proper scraping)
        fast_lo = max(100, lo // 4)
        fast_hi = max(200, hi // 4)
        self._page.wait_for_timeout(random.randint(fast_lo, fast_hi))

    # ══════════════════════════════════════════════════════════════
    #  PROFILE SCRAPING  (all Apify-level fields)
    # ══════════════════════════════════════════════════════════════

    def scrape_profile(self, profile_url: str) -> dict:
        """
        Extract every available field from an Instagram profile page.
        Returns a flat dict that can go straight into a DataFrame row.
        """
        page = self._page
        self.log(f"👤 Scraping profile: {profile_url}")
        self._navigate(profile_url)

        data = {
            "username": extract_username(profile_url),
            "full_name": "",
            "biography": "",
            "pronouns": "",
            "is_business_account": False,
            "is_verified": False,
            "is_private": False,
            "followers_count": 0,
            "following_count": 0,
            "posts_count": 0,
            "highlights_count": 0,
            "highlights": [],
            "external_url": "",
            "threads_url": "",
            "profile_pic_url": "",
            "profile_pic_url_hd": "",
            "date_joined": "",
            "based_in": "",
            "former_usernames": "",
            "profile_url": profile_url,
            "latest_post_url": "",
        }

        try:
            self._extract_json_profile(page, data)
            self._extract_meta_tags(page, data)
            self._extract_header_info(page, data)
            self._extract_highlights(page, data)
            self._extract_about_dialog(page, data)
            self._extract_ads_status(page, data)
            self._extract_profile_pic(page, data)
            self._extract_latest_post(page, data)
        except Exception as e:
            self.log(f"❌ Profile error: {e}")

        # ── Final sanity check: retry meta tags if critical fields are still 0/empty ──
        if data["followers_count"] == 0 or data["posts_count"] == 0:
            self.log("🔄 Profile counts look empty — retrying meta tags…")
            try:
                self._human_delay(2000, 3000)
                self._extract_meta_tags(page, data)
            except Exception:
                pass

        # Last-resort: use og:description via page.evaluate (avoids Playwright locator timeouts)
        if data["followers_count"] == 0:
            try:
                meta_desc = page.evaluate(
                    'document.querySelector(\'meta[property="og:description"]\')?.content || ""'
                )
                if meta_desc:
                    m = re.search(r'([\d,\.km]+)\s*Followers', meta_desc, re.I)
                    if m: data["followers_count"] = parse_count(m.group(1))
                    m = re.search(r'([\d,\.km]+)\s*Following', meta_desc, re.I)
                    if m: data["following_count"] = parse_count(m.group(1))
                    m = re.search(r'([\d,\.km]+)\s*Posts', meta_desc, re.I)
                    if m: data["posts_count"] = parse_count(m.group(1))
                    self.log(f"   ↳ Meta fallback: {data['followers_count']:,} followers")
            except Exception:
                pass

        self.log(
            f"✅ @{data['username']}  ·  "
            f"{data['followers_count']:,} followers  ·  "
            f"{data['posts_count']:,} posts"
        )
        return data

    def _extract_json_profile(self, page, data):
        """Try to find precise counts for followers, following, posts in script tags."""
        try:
            html = page.content()
            # 1. Broad regex for absolute counts in JSON structure (fastest)
            m_foll = re.search(r'"edge_followed_by"\s*:\s*{\s*"count"\s*:\s*(\d+)', html)
            if m_foll:
                data["followers_count"] = int(m_foll.group(1))

            m_folw = re.search(r'"edge_follow"\s*:\s*{\s*"count"\s*:\s*(\d+)', html)
            if m_folw:
                data["following_count"] = int(m_folw.group(1))

            m_posts = re.search(r'"edge_owner_to_timeline_media"\s*:\s*{\s*"count"\s*:\s*(\d+)', html)
            if m_posts:
                data["posts_count"] = int(m_posts.group(1))

            # 2. Extract from application/json script tags (more robust)
            scripts = page.locator('script[type="application/json"]').all_inner_texts()
            for s in scripts:
                if '"edge_followed_by"' in s:
                    try:
                        # Skip if too huge to be a simple profile blob
                        if len(s) < 100: continue
                        obj = json.loads(s)
                        def find_user_node(o):
                            if isinstance(o, dict):
                                if "edge_followed_by" in o and "count" in o["edge_followed_by"]:
                                    return o
                                # Search deeper
                                for k, v in o.items():
                                    res = find_user_node(v)
                                    if res: return res
                            elif isinstance(o, list):
                                for item in o:
                                    res = find_user_node(item)
                                    if res: return res
                            return None
                        
                        usr = find_user_node(obj)
                        if usr:
                            data["followers_count"] = usr.get("edge_followed_by", {}).get("count", data["followers_count"])
                            data["following_count"] = usr.get("edge_follow", {}).get("count", data["following_count"])
                            data["posts_count"] = usr.get("edge_owner_to_timeline_media", {}).get("count", data["posts_count"])
                    except: continue
        except:
            pass

    def _extract_ads_status(self, page, data):
        """Check for active ads in the 'About this account' section."""
        try:
            # 1. Click Options (3-dots)
            dots = page.locator('header svg[aria-label="Options"], header button:has(svg[aria-label="Options"])').first
            if not dots.is_visible(timeout=2000):
                return
            dots.click()
            self._human_delay(800, 1500)
            
            # 2. Click 'About This Account'
            # Instagram often uses different labels, but this is standard for business
            about = page.locator('button:has-text("About this account"), div[role="button"]:has-text("About this account")').first
            if about.is_visible(timeout=1500):
                about.click()
                self._human_delay(1500, 2500)
                
                # Examine modal content
                modal = page.locator('div[role="dialog"]').last
                m_text = modal.inner_text().lower()
                
                if "active ads" in m_text and "not" not in m_text and "none" not in m_text:
                    data["ads_enabled"] = True
                elif "see all ads" in m_text:
                    data["ads_enabled"] = True
                
                # Close modal
                close = page.locator('button:has(svg[aria-label="Close"]), svg[aria-label="Close"]').last
                if close.is_visible(timeout=1000):
                    close.click()
            else:
                # If 'About this account' isn't there, maybe it's under 'Ad library' directly or not available
                # Close the options menu by clicking outside or escape
                page.keyboard.press("Escape")
        except:
            try: page.keyboard.press("Escape")
            except: pass

    # ── Meta tags ──────────────────────────────────────────────

    def _extract_meta_tags(self, page, data):
        """og:title → name, og:description → follower/following/post counts."""
        try:
            title = page.locator('meta[property="og:title"]').get_attribute(
                "content", timeout=3000
            )
            if title:
                m = re.search(r"^(.*?)\s*[\(@]", title)
                if m:
                    data["full_name"] = m.group(1).strip()
        except Exception:
            pass

        try:
            desc = page.locator('meta[property="og:description"]').get_attribute(
                "content", timeout=3000
            )
            if desc:
                parts = desc.split("-")[0].split(",")
                for p in parts:
                    if "Followers" in p:
                        data["followers_count"] = parse_count(p.replace("Followers", ""))
                    elif "Following" in p:
                        data["following_count"] = parse_count(p.replace("Following", ""))
                    elif "Posts" in p:
                        data["posts_count"] = parse_count(p.replace("Posts", ""))
        except Exception:
            pass

        # HD profile pic from og:image
        try:
            og_img = page.locator('meta[property="og:image"]').get_attribute(
                "content", timeout=2000
            )
            if og_img:
                data["profile_pic_url_hd"] = og_img
        except Exception:
            pass

    # ── Header (bio, category, links, verification) ───────────

    def _extract_header_info(self, page, data):
        def _is_link_like(text: str) -> bool:
            t = (text or "").strip().lower()
            if not t:
                return False
            if t.startswith(("http://", "https://", "www.")):
                return True
            if "/" in t and "." in t:
                return True
            return bool(re.search(r"\b[a-z0-9-]+\.[a-z]{2,}\b", t))

        def _normalize_link(href: str) -> str:
            h = (href or "").strip()
            if not h:
                return ""
            if not h.startswith(("http://", "https://", "//", "/")) and re.search(r"[a-z0-9-]+\.[a-z]{2,}", h, flags=re.I):
                h = "https://" + h.lstrip("/")
            if h.startswith("//"):
                h = "https:" + h
            elif h.startswith("/"):
                h = "https://www.instagram.com" + h
            if h.startswith("http://"):
                h = "https://" + h[len("http://"):]

            if "l.instagram.com" in h:
                try:
                    q = parse_qs(urlparse(h).query)
                    target = q.get("u", [""])[0]
                    if target:
                        h = unquote(target)
                except Exception:
                    pass
            if h.startswith("http://"):
                h = "https://" + h[len("http://"):]
            return h

        def _extract_stat_count(label: str) -> int:
            if label == "followers":
                selectors = [
                    'header a[href$="/followers/"] span[title]',
                    'header a[href*="/followers/"] span[title]',
                    'header a[href$="/followers/"] span',
                    'header a[href*="/followers/"] span',
                ]
            elif label == "following":
                selectors = [
                    'header a[href$="/following/"] span[title]',
                    'header a[href*="/following/"] span[title]',
                    'header a[href$="/following/"] span',
                    'header a[href*="/following/"] span',
                ]
            else:
                selectors = [
                    "header section ul li span",
                    "header li span",
                ]

            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    for i in range(min(loc.count(), 16)):
                        node = loc.nth(i)
                        txt = (node.get_attribute("title") or node.inner_text() or "").strip()
                        if not txt:
                            continue
                        if label == "posts" and "post" not in txt.lower() and not re.search(r"[\d,.km]+", txt.lower()):
                            continue
                        m = re.search(r"([\d,\.km]+)", txt.lower())
                        if m:
                            val = parse_count(m.group(1))
                            if val > 0:
                                return val
                except Exception:
                    pass
            return 0

        def _is_stat_line(text: str) -> bool:
            t = (text or "").strip().lower()
            return bool(re.search(r"\b([\d,.km]+)\s+(posts?|followers?|following)\b", t))

        # Pronouns
        try:
            spans = page.locator('header span[dir="auto"]').all()
            for s in spans:
                txt = s.inner_text(timeout=500).strip()
                if "/" in txt and len(txt) < 25:
                    data["pronouns"] = txt
                    break
        except Exception:
            pass

        # Expand all visible "more" controls in profile header/dialog
        try:
            for _ in range(4):
                clicked = False

                more_btns = page.get_by_role(
                    "button",
                    name=re.compile(r"^\s*more\s*$", re.I),
                )
                m_count = more_btns.count()
                for i in range(min(m_count, 8)):
                    btn = more_btns.nth(i)
                    if btn.is_visible(timeout=400):
                        btn.click(timeout=1500)
                        clicked = True
                        self._human_delay(450, 850)

                header_more = page.locator(
                    'header span:has-text("more"), '
                    'header div[role="button"]:has-text("more"), '
                    'header button:has-text("more")'
                )
                h_count = header_more.count()
                for i in range(min(h_count, 8)):
                    btn = header_more.nth(i)
                    try:
                        if btn.is_visible(timeout=300):
                            try:
                                btn.click(timeout=1200, force=True)
                            except Exception:
                                btn.evaluate("el => el.click()")
                            clicked = True
                            self._human_delay(400, 800)
                    except Exception:
                        continue

                # JS fallback: click any header element that is exactly "more".
                try:
                    js_clicked = page.evaluate(
                        """() => {
                            let count = 0;
                            const nodes = document.querySelectorAll('header span, header div[role="button"], header button');
                            for (const n of nodes) {
                                const t = (n.textContent || '').trim().toLowerCase();
                                if (t === 'more') {
                                    n.click();
                                    count += 1;
                                }
                            }
                            return count;
                        }"""
                    )
                    if js_clicked and js_clicked > 0:
                        clicked = True
                        self._human_delay(300, 600)
                except Exception:
                    pass

                if not clicked:
                    break
        except Exception:
            pass

        try:
            header_text = page.locator("header").inner_text(timeout=3000)

            # Prefer dedicated stat nodes (more accurate than rounded/meta values).
            exact_followers = _extract_stat_count("followers")
            exact_following = _extract_stat_count("following")
            exact_posts = _extract_stat_count("posts")
            if exact_followers > 0:
                data["followers_count"] = exact_followers
            if exact_following >= 0 and exact_following > 0:
                data["following_count"] = exact_following
            if exact_posts > 0:
                data["posts_count"] = exact_posts

            # Fallback stats from visible text
            if data["followers_count"] == 0:
                m = re.search(r"(?i)([\d,\.km]+)\s*followers", header_text)
                if m:
                    data["followers_count"] = parse_count(m.group(1))
            if data["following_count"] == 0:
                m = re.search(r"(?i)([\d,\.km]+)\s*following", header_text)
                if m:
                    data["following_count"] = parse_count(m.group(1))
            # Always use explicit "X posts" pattern to avoid picking numbers from highlight names.
            m = re.search(r"(?i)\b([\d,\.km]+)\s*posts?\b", header_text)
            if m:
                data["posts_count"] = parse_count(m.group(1))

            # Parse bio from header auto-direction spans to avoid highlights/footer noise.
            bio_candidates = []
            highlight_names = set()
            try:
                h_anchors = page.locator('header a[href*="/stories/highlights/"]').all()
                for a in h_anchors:
                    try:
                        t = (a.inner_text() or "").strip()
                        if t:
                            highlight_names.add(t.lower())
                    except Exception:
                        continue
            except Exception:
                pass

            bio_spans = page.locator('header span[dir="auto"]').all()
            for s in bio_spans:
                try:
                    txt = (s.inner_text(timeout=500) or "").strip()
                except Exception:
                    continue
                if not txt:
                    continue
                for part in txt.split("\n"):
                    part = part.strip()
                    lf = part.lower()
                    if not part:
                        continue
                    if part in {data.get("username", ""), data.get("full_name", "")}:
                        continue
                    if _is_stat_line(part):
                        continue
                    if _is_link_like(part):
                        continue
                    if lf in {"more", "follow", "following", "message", "contact", "share profile"}:
                        continue
                    if lf in highlight_names:
                        continue
                    bio_candidates.append(part)

            if bio_candidates:
                dedup = []
                for b in bio_candidates:
                    b = re.sub(r"(?:\.\.\.|…)\s*$", "", b).strip()
                    if not b:
                        continue
                    # prefer non-truncated variant when both exist
                    short = b.rstrip(".").rstrip("…").rstrip("...")
                    replaced = False
                    for i, existing in enumerate(dedup):
                        ex_short = existing.rstrip(".").rstrip("…").rstrip("...")
                        if short == ex_short:
                            if len(b) > len(existing):
                                dedup[i] = b
                            replaced = True
                            break
                    if not replaced:
                        dedup.append(b)
                data["biography"] = "\n".join(dedup)

            # Parse category + fallback bio from remaining header lines
            lines = header_text.split("\n")
            clean = []
            for ln in lines:
                ln = ln.strip()
                lf = ln.lower()
                if not ln or ln == data["username"] or ln == data["full_name"]:
                    continue
                if any(
                    kw in lf
                    for kw in [
                        "followers", "following", "posts", "follow",
                        "message", "and ", "threads", "more",
                    ]
                ):
                    continue
                if _is_link_like(ln):
                    continue
                clean.append(ln)

            if clean and not data.get("biography"):
                first = clean[0]
                # Common words that are definitely categories
                known_cats = {"personal blog", "public figure", "musician/band", "artist", "shopping & retail", "health/beauty", "video creator", "entrepreneur"}
                is_known = first.lower() in known_cats
                if (is_known or (len(first.split()) <= 4 and not _is_link_like(first) and "@" not in first and "." not in first)):
                    data["category"] = first
                    data["is_business_account"] = True
                    data["biography"] = " | ".join(clean[1:])
                else:
                    data["biography"] = " | ".join(clean)

            # Fallback for category
            if not data.get("category"):
                cat_el = page.locator('header a[href*="/explore/Locations/"], header div[dir="auto"]').all()
                for el in cat_el:
                    txt = el.inner_text().strip()
                    tlf = txt.lower()
                    if (
                        txt
                        and len(txt.split()) <= 4
                        and txt != data.get("full_name")
                        and "\n" not in txt
                        and not _is_link_like(txt)
                        and tlf not in {"follow", "following", "message", "share profile", "contact"}
                    ):
                        data["is_business_account"] = True
                        break
        except Exception:
            pass

        # Links
        try:
            # Open "and X more" links dialog if present so all external links become visible.
            try:
                for _ in range(3):
                    clicked_any = False
                    and_more_candidates = page.locator(
                        'header button:text-matches("and\\s+\\d+\\s+more", "i"), '
                        'header div[role="button"]:text-matches("and\\s+\\d+\\s+more", "i"), '
                        'header *:text-matches("and\\s+\\d+\\s+more", "i"), '
                        'header button:has-text("and")'
                    )
                    for i in range(min(and_more_candidates.count(), 8)):
                        and_more = and_more_candidates.nth(i)
                        try:
                            if not and_more.is_visible(timeout=500):
                                continue
                        except Exception:
                            continue

                        clicked = False
                        try:
                            and_more.click(timeout=1500, force=True)
                            clicked = True
                        except Exception:
                            pass
                        if not clicked:
                            try:
                                and_more.evaluate("el => el.click()")
                                clicked = True
                            except Exception:
                                pass
                        if clicked:
                            clicked_any = True
                            self._human_delay(500, 900)

                    # DOM-level fallback: click any header element with text like "and 2 more"
                    try:
                        js_clicked = page.evaluate(
                            """() => {
                                let n = 0;
                                const rx = /and\\s+\\d+\\s+more/i;
                                for (const el of document.querySelectorAll('header button, header [role="button"], header a, header span, header div')) {
                                    const t = (el.textContent || '').trim();
                                    if (rx.test(t)) { el.click(); n += 1; }
                                }
                                return n;
                            }"""
                        )
                        if js_clicked and js_clicked > 0:
                            clicked_any = True
                            page.wait_for_timeout(700)
                    except Exception:
                        pass

                    if not clicked_any:
                        break
            except Exception:
                pass

            anchors = page.locator("header a, [role='dialog'] a, div[role='dialog'] a").all()
            bio_links = []
            threads_links = []

            for a in anchors:
                href = _normalize_link(a.get_attribute("href") or "")
                if not href:
                    continue

                h = href.lower()
                if "threads.net" in h or "threads.com" in h:
                    threads_links.append(href)
                    continue

                if any(seg in h for seg in ["/p/", "/reel/", "/stories/", "/explore/", "/accounts/", "/direct/"]):
                    continue
                if "instagram.com/" in h and "l.instagram.com" not in h:
                    continue
                if h.startswith(("http://", "https://")):
                    bio_links.append(href)

            # Hard fallback: parse l.instagram redirect links directly from page HTML.
            try:
                html = page.content()
                for m in re.findall(r'https?:\\\\?/\\\\?/l\\.instagram\\.com/[^"\\s<]+|https?://l\\.instagram\\.com/[^"\\s<]+', html, flags=re.I):
                    raw = m.replace("\\/", "/")
                    n = _normalize_link(raw)
                    if n:
                        nl = n.lower()
                        if "threads.net" in nl or "threads.com" in nl:
                            threads_links.append(n)
                        elif "instagram.com/p/" not in nl and "instagram.com/reel/" not in nl and "instagram.com/" not in nl:
                            bio_links.append(n)
            except Exception:
                pass

            # Also scan visible header/dialog text for plain URLs/domains shown after clicking "more".
            try:
                text_blocks = []
                for sel in ["header", "[role='dialog']", "div[role='dialog']"]:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        text_blocks.append(loc.first.inner_text(timeout=1500) or "")
                joined = "\n".join(text_blocks)
                for m in re.findall(r"(https?://[^\s]+|(?:www\.)?[a-z0-9-]+\.[a-z]{2,}(?:/[^\s]*)?)", joined, flags=re.I):
                    cand = _normalize_link(m.strip(".,);]}>\"'"))
                    if not cand:
                        continue
                    cl = cand.lower()
                    # Guard against broken partial domains like "www.foo.bar" where "bar" is not a real TLD.
                    try:
                        host = (urlparse(cand).netloc or "").lower()
                        tld = host.rsplit(".", 1)[-1] if "." in host else ""
                        if tld and tld not in {"com", "net", "org", "in", "co", "io", "ai", "me", "us"}:
                            continue
                    except Exception:
                        pass
                    if "instagram.com/p/" in cl or "instagram.com/reel/" in cl:
                        continue
                    if "threads.net" in cl or "threads.com" in cl:
                        threads_links.append(cand)
                    elif "instagram.com/" not in cl:
                        bio_links.append(cand)
            except Exception:
                pass

            # If category accidentally contains a link/domain, move it to external links.
            category_text = (data.get("category") or "").strip()
            if _is_link_like(category_text):
                moved = category_text
                if not moved.startswith(("http://", "https://")):
                    moved = "https://" + moved
                bio_links.append(moved)
                data["category"] = ""
                data["is_business_account"] = False

            # Dedupe links while preferring richer (longer) URLs for same host+path.
            compact = {}
            for link in bio_links:
                n = _normalize_link(link)
                if not n:
                    continue
                p = urlparse(n)
                key = (p.netloc.lower(), p.path.rstrip("/").lower())
                prev = compact.get(key)
                if not prev or len(n) > len(prev):
                    compact[key] = n
            data["external_url"] = ", ".join(compact.values())

            t_compact = {}
            for link in threads_links:
                n = _normalize_link(link)
                if not n:
                    continue
                p = urlparse(n)
                key = (p.netloc.lower(), p.path.rstrip("/").lower())
                prev = t_compact.get(key)
                if not prev or len(n) > len(prev):
                    t_compact[key] = n
            if t_compact:
                data["threads_url"] = ", ".join(t_compact.values())

            # Close any link dialog opened by "and X more" so subsequent extractors can interact with header.
            try:
                for _ in range(2):
                    if page.locator('div[role="dialog"]').count() > 0:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(250)
                    else:
                        break
            except Exception:
                pass
        except Exception:
            pass

        # Verified badge
        try:
            html = page.locator("header").inner_html()
            if "Verified" in html or page.locator(
                'svg[aria-label="Verified"]'
            ).is_visible(timeout=1000):
                data["is_verified"] = True
        except Exception:
            pass

        # Private account
        try:
            if page.locator('text="This account is private"').is_visible(timeout=1000):
                data["is_private"] = True
        except Exception:
            pass

    def _extract_highlights(self, page, data):
        try:
            names = []
            canvases = page.locator("main canvas").all()
            for c in canvases:
                try:
                    txt = c.locator("xpath=../..").inner_text(timeout=500).strip()
                    if txt and "\n" not in txt and not txt.isdigit():
                        names.append(txt)
                    elif not txt:
                        adj = c.locator("xpath=../../following-sibling::div").first
                        adj_txt = adj.inner_text(timeout=500).strip()
                        if adj_txt and not adj_txt.isdigit():
                            names.append(adj_txt)
                except Exception:
                    pass
            data["highlights"] = list(dict.fromkeys(names))  # dedupe, keep order
            data["highlights_count"] = len(data["highlights"])
        except Exception:
            pass

    # ── About this account (3-dot menu) ────────────────────────

    def _extract_about_dialog(self, page, data):
        try:
            # 1) Click the 3-dots options control.
            opened_menu = False
            for _ in range(3):
                try:
                    opened_menu = bool(page.evaluate(
                        """() => {
                            const controls = document.querySelectorAll('header button, header [role="button"], button, [role="button"]');
                            for (const el of controls) {
                                const a = (el.getAttribute('aria-label') || '').toLowerCase();
                                const t = (el.textContent || '').trim().toLowerCase();
                                if (a.includes('option') || t === 'more options' || t === 'options') {
                                    try { el.click(); return true; } catch (e) {}
                                }
                            }
                            return false;
                        }"""
                    ))
                except Exception:
                    opened_menu = False
                if opened_menu:
                    break
                page.wait_for_timeout(300)

            if not opened_menu:
                return
            page.wait_for_timeout(700)

            # 2) Click "About this account" inside menu dialog.
            clicked_about = False
            for _ in range(5):
                try:
                    clicked_about = bool(page.evaluate(
                        """() => {
                            const dialogs = document.querySelectorAll('div[role="dialog"]');
                            for (const d of dialogs) {
                                const rows = d.querySelectorAll('button, [role="button"]');
                                for (const r of rows) {
                                    const t = (r.textContent || '').trim().toLowerCase();
                                    if (t.includes('about this account')) {
                                        try { r.click(); return true; } catch (e) {}
                                    }
                                }
                            }
                            return false;
                        }"""
                    ))
                except Exception:
                    clicked_about = False
                if clicked_about:
                    break
                page.wait_for_timeout(450)

            if not clicked_about:
                # Playwright fallback selectors in case DOM click missed the menu row.
                try:
                    about_loc = page.locator('div[role="dialog"] button, div[role="dialog"] [role="button"]').filter(
                        has_text=re.compile("About this account", re.I)
                    ).first
                    if about_loc.count() and about_loc.is_visible(timeout=900):
                        try:
                            about_loc.click(timeout=1600, force=True)
                        except Exception:
                            about_loc.evaluate("el => el.click()")
                        clicked_about = True
                except Exception:
                    pass

            if not clicked_about:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return
            page.wait_for_timeout(1100)

            # 3) Extract fields from About dialog text.
            about_text = ""
            try:
                d = page.locator('div[role="dialog"]').filter(
                    has_text=re.compile("Date joined|Account based in|Former usernames", re.I)
                ).first
                if d.count():
                    about_text = d.inner_text(timeout=2000)
                else:
                    dialogs = page.locator('div[role="dialog"]')
                    for i in range(min(dialogs.count(), 3)):
                        txt = dialogs.nth(i).inner_text(timeout=1000)
                        if re.search(r"Date joined|Account based in|Former usernames", txt, re.I):
                            about_text = txt
                            break
            except Exception:
                about_text = ""

            if about_text:
                m = re.search(r"Date joined\s*\n([^\n]+)", about_text, re.I)
                if m:
                    data["date_joined"] = m.group(1).strip()
                m = re.search(r"Account based in\s*\n([^\n]+)", about_text, re.I)
                if m:
                    data["based_in"] = m.group(1).strip()
                m = re.search(r"Former usernames\s*\n([^\n]+)", about_text, re.I)
                if m:
                    data["former_usernames"] = m.group(1).strip()

            # 4) Close dialogs.
            for _ in range(3):
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(250)
                except Exception:
                    break
        except Exception:
            pass

    # ── Reels tab count ────────────────────────────────────────

    # ── Profile picture ────────────────────────────────────────

    def _extract_profile_pic(self, page, data):
        try:
            img = page.locator("header img").first
            if img.is_visible(timeout=2000):
                src = img.get_attribute("src")
                if src:
                    data["profile_pic_url"] = src
        except Exception:
            pass

    # ── Latest post URL ────────────────────────────────────────

    def _extract_latest_post(self, page, data):
        try:
            a = page.locator('a[href*="/p/"]').first
            if a.is_visible(timeout=2000):
                href = a.get_attribute("href") or ""
                if not href.startswith("http"):
                    href = "https://www.instagram.com" + href
                data["latest_post_url"] = href
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  MEDIA DEEP-SCRAPE  (posts + reels via modal navigation)
    # ══════════════════════════════════════════════════════════════

    def _build_media_from_cache(self, sc: str, href: str, owner: str) -> dict | None:
        """Build a complete media dict from sniffer cache. Returns None if insufficient data."""
        cached = self._media_cache.get(sc)
        if not cached:
            return None
        # Require at minimum: likes or caption — otherwise the cache is too sparse
        if not cached.get("likes") and not cached.get("caption"):
            return None

        caption = cached.get("caption", "")
        raw_ts = cached.get("timestamp", "")
        timestamp_iso = ""
        date_str = ""
        if raw_ts:
            try:
                from datetime import datetime as _dt
                dt = _dt.fromtimestamp(int(raw_ts))
                timestamp_iso = dt.isoformat()
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                timestamp_iso = raw_ts
                date_str = raw_ts[:10] if len(raw_ts) >= 10 else ""

        is_reel = "/reel/" in href
        media_type = cached.get("media_type", "Reel" if is_reel else "Photo")

        return {
            "short_code": sc,
            "media_type": media_type,
            "caption": caption.replace("\n", " | ") if caption else "",
            "hashtags": extract_hashtags(caption),
            "keywords": extract_keywords(caption),
            "mentions": extract_mentions(caption),
            "tagged_users": cached.get("tagged_users", 0),
            "likes_count": cached.get("likes", "N/A"),
            "comments_count": cached.get("comments", "N/A"),
            "views_count": cached.get("views", ""),
            "reposts_count": cached.get("reposts", "N/A"),
            "saves_count": cached.get("saves", "N/A"),
            "is_pinned": cached.get("is_pinned", False),
            "is_sponsored": cached.get("is_sponsored", False),
            "timestamp": timestamp_iso,
            "date": date_str,
            "location_id": cached.get("location_id", ""),
            "audio_title": cached.get("audio_title", ""),
            "display_url": cached.get("display_url", ""),
            "video_url": cached.get("video_url", ""),
            "carousel_count": cached.get("carousel_count", 0),
            "carousel_urls": cached.get("carousel_urls", ""),
            "owner_username": cached.get("owner_username", owner),
        }

    def scrape_media(self, profile_url: str, limit: int = 12, username: str = "", skip: int = 0, on_media_item=None) -> list[dict]:
        """
        Click the first post / reel and navigate with ArrowRight,
        extracting rich data from each modal.
        """
        # limit < 0 is our internal flag to skip media entirely (though usually handled in server.py)
        if limit < 0:
            return []

        page = self._page
        username = username or extract_username(profile_url)
        limit_desc = "all" if limit == 0 else f"up to {limit}"
        skip_desc = f" (skipping first {skip})" if skip > 0 else ""
        self.log(f"📸 Deep-scraping {limit_desc} media items for @{username}{skip_desc}…")

        self._navigate(profile_url)

        # Load all posts by scrolling to bottom until no more load
        self.log("📜 Loading all posts by scrolling...")
        scroll_attempts = 0
        stale_rounds = 0  # how many consecutive scrolls yielded zero new unique posts
        max_scrolls = 2000 if limit == 0 or limit > 500 else 200  # More scrolls for larger requests
        hrefs = []  # unique post hrefs, built incrementally
        seen_hrefs = set()
        grid_metrics = {}  # href -> {'likes': str, 'comments': str}

        def _collect_hrefs_from_page():
            """Scan current DOM for post links and add new ones to hrefs."""
            post_links = page.locator('a[href*="/p/"], a[href*="/reel/"]')
            new_count = 0
            for link in post_links.all():
                h = link.get_attribute('href')
                if not h:
                    continue
                # Normalise: strip query params for dedup, keep original for navigation
                clean = h.split('?')[0].rstrip('/') + '/'
                if clean not in seen_hrefs:
                    seen_hrefs.add(clean)
                    hrefs.append(h)
                    grid_metrics[clean] = {}
                    grid_metrics[h] = {}
                    new_count += 1
            return new_count

        # Initial collection before any scrolling
        _collect_hrefs_from_page()
        target_count = (limit + skip) if limit > 0 else 999_999

        while scroll_attempts < max_scrolls and len(hrefs) < target_count:
            # Scroll to bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._human_delay(2000, 4000)
            scroll_attempts += 1

            new = _collect_hrefs_from_page()

            if new == 0:
                stale_rounds += 1
                if stale_rounds >= 3:
                    # Give one final long wait before giving up
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    self._human_delay(5000, 8000)
                    bonus = _collect_hrefs_from_page()
                    if bonus == 0:
                        break
                    else:
                        stale_rounds = 0
            else:
                stale_rounds = 0

            # Log progress every 10 scrolls
            if scroll_attempts % 10 == 0:
                self.log(f"   ...scrolled {scroll_attempts} times, {len(hrefs)} unique items so far...")

        self.log(f"✅ Loaded {len(hrefs)} unique items after {scroll_attempts} scrolls.")

        self.log(f"📋 Collected {len(hrefs)} unique post URLs.")

        # Extract view counts for reels from the Reels tab 
        # By navigating directly to /reels/ as suggested by verification
        grid_views = {}
        try:
            reels_url = profile_url.rstrip("/") + "/reels/"
            self.log(f"🎬 Navigating to Reels tab: {reels_url}")
            page.goto(reels_url, timeout=30000, wait_until="domcontentloaded")
            self._human_delay(3000, 5000)
            
            # Scroll to load thumbnails — dynamic scroll count based on total posts
            # Each scroll loads ~12 reels, so we need enough scrolls for all posts
            reel_scroll_count = max(8, len(hrefs) // 8 + 3) # More scrolls to be safe
            self.log(f"   (Triggered bulk view fetch via Reels tab — {reel_scroll_count} scrolls)")
            stale_reel = 0
            prev_reel_count = 0
            for rs in range(reel_scroll_count):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self._human_delay(1500, 3000)
                # Aggressive scroll to ensure trigger
                page.mouse.wheel(0, 2000)
                self._human_delay(500, 1000)
                
                cur_reel_count = page.locator('a[href*="/reel/"]').count()
                if cur_reel_count == prev_reel_count and cur_reel_count > 0:
                    stale_reel += 1
                    if stale_reel >= 4: # Be more patient
                        break
                else:
                    stale_reel = 0
                prev_reel_count = cur_reel_count
            
            reel_links = page.locator('a[href*="/reel/"]').all()
            for link in reel_links:
                href_val = link.get_attribute('href')
                if href_val and "/reel/" in href_val:
                    # Clean the href to remove query params for steady lookup
                    clean_href = href_val.split('?')[0].rstrip('/') + '/'
                    try:
                        # 1. Try specifically for span/div that often holds the play count
                        # On Reels tab, the ONLY text overlay is usually the play count
                        text = (link.inner_text() or "").strip().lower()
                        # Extract number pattern (e.g. 253K)
                        m = re.search(r'([\d,\.km]+)', text)
                        
                        if not m:
                            # Fallback: look for aria-labels or nested spans
                            al = (link.get_attribute('aria-label') or "").lower()
                            m = re.search(r'([\d,\.km]+)\s*(?:views|plays)', al)
                        
                        if m:
                            val = m.group(1)
                            grid_views[clean_href] = str(parse_count(val))
                            grid_views[href_val] = grid_views[clean_href]
                            grid_views[extract_shortcode(href_val)] = grid_views[clean_href]
                    except Exception:
                        pass
            self.log(f"📊 Captured view counts for {len(grid_views)} reels.")
        except Exception as e:
            self.log(f"⚠️ Reels extraction failed: {e}")
        
        # Go back to the main profile to collect post URLs (if not already done)
        self._navigate(profile_url)

        # If limit is 0, scrape all
        if limit == 0:
            limit = len(hrefs)

        # Mimic human scroll
        page.mouse.wheel(0, 400)
        self._human_delay(1000, 2000)
        page.mouse.wheel(0, -200)
        self._human_delay(1000, 2000)

        # ── Deep & Persistent extraction: visit every post with retries ──
        collected = []
        target_hrefs = hrefs[skip:] if skip < len(hrefs) else []
        visited_count = 0
        failed_count = 0
        seen_scs = set()  # dedup by shortcode
        
        if skip > 0:
            self.log(f"⏭️ Skipping first {skip} items…")

        self.log(f"🔍 Starting deep extraction of {min(limit, len(target_hrefs))} posts (visit every URL)…")

        for i, href in enumerate(target_hrefs):
            if len(collected) >= limit and limit != 0:
                break

            sc = extract_shortcode(href)

            # Dedup: skip if we already collected this shortcode
            if sc in seen_scs:
                continue

            # ── Cool-down every 25 page visits for account safety ──
            if visited_count > 0 and visited_count % 25 == 0:
                pause = random.randint(120, 180)
                self.log(f"⏸️ Safety cool-down: resting {pause}s after {visited_count} visits…")
                self.progress(len(collected), limit, f"⏸️ Cool-down ({pause}s)…")
                _time.sleep(pause)

            # ── Visit with 3-retry system ──
            full_url = "https://www.instagram.com" + href
            entry = None
            for attempt in range(1, 4):
                try:
                    page.goto(full_url, timeout=60000, wait_until="domcontentloaded")
                    self._human_delay(3000, 5000)

                    # ── Rate-limit / login-wall detection ──
                    try:
                        body_text = (page.locator("body").inner_text(timeout=2000) or "").lower()
                        if any(phrase in body_text for phrase in [
                            "please wait", "try again later", "rate limit",
                            "suspicious activity", "temporarily blocked",
                        ]):
                            self.log(f"🚨 Rate limit detected! Pausing 10 minutes…")
                            self.progress(len(collected), limit, "🚨 Rate limit — pausing 10m…")
                            _time.sleep(600)
                            page.reload(timeout=30000)
                            self._human_delay(3000, 5000)
                        # Check for login wall
                        login_btn = page.locator('a[href="/accounts/login/"]')
                        if login_btn.count() > 0 and login_btn.first.is_visible(timeout=1000):
                            self.log(f"🔒 Login wall detected! Pausing 5 minutes…")
                            self.progress(len(collected), limit, "🔒 Login wall — pausing 5m…")
                            _time.sleep(300)
                            page.reload(timeout=30000)
                            self._human_delay(3000, 5000)
                    except Exception:
                        pass  # detection failed — continue anyway

                    entry = self._extract_single_media(page, full_url, href, username, grid_views, grid_metrics)
                    break  # success — exit retry loop

                except Exception as e:
                    if attempt < 3:
                        wait = 10 * attempt
                        self.log(f"   ⚠️ Attempt {attempt}/3 failed for {href}: {e}. Retrying in {wait}s…")
                        _time.sleep(wait)
                    else:
                        self.log(f"   ❌ All 3 attempts failed for {href}: {e}")

            if entry:
                seen_scs.add(sc)
                collected.append(entry)
                visited_count += 1
                self.progress(len(collected), limit, f"Media {len(collected)}/{limit}")
                self.log(f"   📌 [{len(collected)}/{limit}] {entry['media_type']}: {href}")
                if on_media_item:
                    on_media_item(entry)
            else:
                # All retries failed — try sniffer cache as last resort
                fallback = self._build_media_from_cache(sc, href, username)
                if fallback:
                    seen_scs.add(sc)
                    collected.append(fallback)
                    self.log(f"   🔄 [{len(collected)}/{limit}] Fallback from cache: {href}")
                    if on_media_item:
                        on_media_item(fallback)
                else:
                    failed_count += 1
                    self.log(f"   💀 Permanently skipped: {href}")

            # Small human-like delay between posts
            self._human_delay(2000, 4000)

        self.log(f"✅ Collected {len(collected)} media items ({visited_count} visited, {failed_count} failed).")
        return collected

    # ── Single media extraction (inside modal) ─────────────────
    
    def _extract_single_media(self, page, current_url: str, href: str, owner: str, grid_views: dict = None, grid_metrics: dict = None) -> dict:
        """
        Extract detailed metadata for a single post/reel.
        """
        is_reel = "/reel/" in href
        sc = extract_shortcode(href)

        # Trigger background data fetch by hovering if it's a video/reel
        try:
            video_el = page.locator("video").first
            if video_el.is_visible(timeout=1000):
                video_el.hover()
        except: pass

        # Intelligent Wait: Poll the network cache for up to 4 seconds
        # This allows us to move instantly if data arrives, or wait if the API is slow.
        start_wait = _time.time()
        while _time.time() - start_wait < 4:
            if sc in self._media_cache:
                cached = self._media_cache[sc]
                if cached.get("views") or cached.get("likes"):
                    break
            _time.sleep(0.5)

        res = {
            "short_code": sc,
            "media_type": "",
            "caption": "",
            "hashtags": [],
            "keywords": "",
            "mentions": [],
            "tagged_users": 0,
            "likes_count": "",
            "comments_count": "",
            "views_count": "",
            "reposts_count": "",
            "saves_count": "",
            "is_pinned": False,
            "is_sponsored": False,
            "timestamp": "",
            "date": "",
            "location_id": "",
            "audio_title": "",
            "display_url": "",
            "video_url": "",
            "carousel_count": 0,
            "carousel_urls": "",
            "owner_username": owner,
        }
        
        # Determine the container (article or modal)
        container = page.locator("article")
        if not container.is_visible():
            container = page.locator('div[role="dialog"]').locator("article").first
        if not container.is_visible():
            container = page.locator("main")

        # Expand caption ("more" button)
        try:
            more_btns = container.locator('span, div[role="button"], button').filter(has_text=re.compile(r"^more$", re.I)).all()
            for btn in more_btns:
                if btn.is_visible(timeout=500):
                    btn.click(timeout=1000)
                    page.wait_for_timeout(300)
        except Exception:
            pass

        # ── Caption ──
        caption = ""
        try:
            # 1. H1 is often used for accessibility caption
            for h in container.locator("h1").all():
                txt = h.inner_text().strip()
                if txt and txt != owner: # Avoid picking up just the username
                    caption = txt
                    break
            
            # 2. Main caption text is usually in a span inside article
            if not caption:
                # Look for the first large block of text that isn't the owner or stats
                spans = container.locator('span[dir="auto"]').all()
                for s in spans:
                    t = s.inner_text().strip()
                    if t and t != owner and len(t) > 10:
                        # Heuristic: caption is usually the longest span starting near the top
                        if len(t) > len(caption):
                            caption = t
        except Exception:
            pass

        # ── Mentions (from caption) ──
        try:
            mentions_list = []
            if caption:
                mentions_list.extend(re.findall(r"@([\w\.]+)", caption))
            
            # Fallback: check <a> tags within the caption elements for profile links
            cap_links = container.locator('h1 a, span[dir="auto"] a').all()
            for alink in cap_links:
                try:
                    href_val = alink.get_attribute("href") or ""
                    if href_val and "/" in href_val and not any(k in href_val for k in ["#", "/p/", "/reel/", "/explore/"]):
                        m_user = re.search(r"^/([^/]+)/$", href_val)
                        if m_user:
                            mentions_list.append(m_user.group(1))
                except: continue
            
            res["mentions"] = sorted(list(set(mentions_list)))
        except Exception:
            pass

        # ── Alt text / accessibility caption ──
        alt_text = ""
        try:
            img_with_alt = container.locator("img[alt]").first
            if img_with_alt.is_visible(timeout=500):
                alt_text = img_with_alt.get_attribute("alt") or ""
        except Exception:
            pass

        # ── Date / timestamp ──
        timestamp_iso = ""
        date_str = ""
        try:
            time_el = container.locator("time").first
            if time_el.is_visible(timeout=1000):
                dt = time_el.get_attribute("datetime")
                if dt:
                    timestamp_iso = dt
                    date_str = dt[:10]
        except Exception:
            pass

        likes = ""
        views = ""
        comments = ""
        location_name = ""
        location_id = ""
        # Pre-populate from sniffer cache
        _sc_cache = self._media_cache.get(sc, {})
        audio_title = _sc_cache.get("audio_title", "")
        pinned = _sc_cache.get("is_pinned", False)
        sponsored = _sc_cache.get("is_sponsored", False)
        video_url = ""
        display_url = ""
        carousel_count = 0
        carousel_urls_list = []
        tagged_users_count = 0

        # ── Tagged Users ──
        try:
            # Look for "In this photo" or "Tagged" icons/buttons
            tag_btns = container.locator('button[aria-label*="tagged"], button[aria-label*="person"], [role="button"]:has-text("Tagged")').all()
            # Often it's a single button that opens a list, or multiple if hovering
            # Better: check if we can find "tagged_user" in JSON (handled below)
            tagged_users_count = len(tag_btns)
        except: pass

        # ── Location ──
        try:
            # 1. Look for explicit explore link
            loc = container.locator('a[href*="/explore/locations/"]').first
            if not loc.is_visible(timeout=300):
                # 2. Look for common location header classes or positions
                # Often the second link in the header after the username
                loc = container.locator('header a').nth(1)
            
            if loc.is_visible(timeout=500):
                txt = loc.inner_text().strip()
                # Verify it's not a stat or the username
                if txt and txt != owner and not re.search(r'posts|followers|following', txt.lower()):
                    loc_href = loc.get_attribute("href") or ""
                    m = re.search(r"/locations/(\d+)", loc_href)
                    if m:
                        location_id = m.group(1)
        except Exception:
            pass

        # ── Audio (reels) ──
        try:
            audio = container.locator('a[href*="/reels/audio/"]').first
            if audio.is_visible(timeout=500):
                audio_title = audio.inner_text().strip()
        except Exception:
            pass

        # ── Engagement metrics (likes, views, comments, reposts, saves) ──
        try:
            json_like = None
            json_comment = None
            json_view = None
            json_repost = None
            json_save = None

            # 0. Check Network Cache (Most Accurate - Sniffed from background traffic)
            sc = extract_shortcode(current_url or href)
            cached = self._media_cache.get(sc)
            if cached:
                if cached.get("likes"): json_like = cached["likes"]
                if cached.get("comments"): json_comment = cached["comments"]
                if cached.get("views"): json_view = cached["views"]
                if cached.get("reposts"): json_repost = cached["reposts"]
                if cached.get("saves"): json_save = cached["saves"]

            # 1. Direct JSON Extraction (From page source scripts)
            json_video_url = None
            json_display_url = None
            if not (json_like and json_comment and json_view):
                try:
                    def find_metric_in_obj(o, target_sc):
                        if isinstance(o, dict):
                            if o.get("shortcode") == target_sc or o.get("code") == target_sc:
                                return o
                            if 'media' in o and isinstance(o['media'], dict):
                                m = o['media']
                                if m.get('code') == target_sc or m.get('shortcode') == target_sc:
                                    return m
                            for v in o.values():
                                res_obj = find_metric_in_obj(v, target_sc)
                                if res_obj: return res_obj
                        elif isinstance(o, list):
                            for item in o:
                                res_obj = find_metric_in_obj(item, target_sc)
                                if res_obj: return res_obj
                        return None

                    scripts = page.locator('script[type="application/json"]').all_inner_texts()
                    for content in scripts:
                        if sc in content:
                            try:
                                if len(content) < 50: continue
                                j_data = json.loads(content)
                                pm = find_metric_in_obj(j_data, sc)
                                if pm:
                                    # Likes
                                    l = pm.get("like_count") or (pm.get("edge_media_preview_like") or {}).get("count")
                                    if l is not None: json_like = str(int(l))
                                    # Comments
                                    c = pm.get("comment_count") or (pm.get("edge_media_to_comment") or {}).get("count")
                                    if c is not None: json_comment = str(int(c))
                                    # Views
                                    v = pm.get("play_count") or pm.get("view_count") or pm.get("video_view_count")
                                    if v is not None: json_view = str(int(v))
                                    # Reposts
                                    rp = pm.get("reshare_count") or pm.get("share_count") or pm.get("repost_count") or (pm.get("edge_media_to_reshare") or {}).get("count")
                                    if rp is not None: json_repost = str(int(rp))
                                    # Saves
                                    sv = pm.get("save_count") or pm.get("saved_count") or (pm.get("edge_media_to_save") or {}).get("count")
                                    if sv is not None: json_save = str(int(sv))
                                    
                                    # Video URL from JSON (actual downloadable URL)
                                    vu = pm.get("video_url")
                                    if not vu:
                                        vv = pm.get("video_versions")
                                        if isinstance(vv, list) and vv:
                                            vu = vv[0].get("url")
                                    if vu and not vu.startswith("blob:"):
                                        json_video_url = vu

                                    # Display URL from JSON
                                    du = pm.get("thumbnail_src") or pm.get("display_url")
                                    if not du:
                                        iv = pm.get("image_versions2", {}).get("candidates")
                                        if isinstance(iv, list) and iv:
                                            du = iv[0].get("url")
                                    if du:
                                        json_display_url = du

                                    if json_like or json_comment or json_view: break
                            except:
                                continue
                except Exception:
                    pass

            # 2. Targeted DOM Extraction (Hierarchy: Action Buttons > Specialized Patterns > Generic Text)
            dom_likes = ""
            dom_comments = ""
            dom_views = ""
            dom_reposts = ""
            dom_saves = ""

            # Scan the interaction area specifically (usually right-side panel or bottom-left)
            try:
                # Likes: ARIA Label is most accurate
                heart = container.locator('svg[aria-label="Like"], svg[aria-label="Unlike"], button:has(svg[aria-label="Like"])').first
                if heart.is_visible(timeout=500):
                    # Check parent button aria-label: "1,234 likes"
                    parent_btn = heart.locator('xpath=./ancestor-or-self::button')
                    label = (parent_btn.get_attribute("aria-label") or "").lower()
                    m = re.search(r'([\d,\.km]+)\s+likes?', label)
                    if m: dom_likes = str(parse_count(m.group(1)))
                    
                # Likes: "Liked by X and Y others"
                if not dom_likes:
                    # Look for the 'Liked by' text block
                    liked_by_loc = container.locator('xpath=.//*[contains(text(), "Liked by")]').first
                    if liked_by_loc.is_visible(timeout=500):
                        txt = liked_by_loc.inner_text().strip()
                        # Extract the 'others' count
                        m_others = re.search(r'and\s+([\d,\.km]+)\s+others', txt, re.I)
                        if m_others:
                            count = parse_count(m_others.group(1))
                            # Add the named users. Usually "Liked by [User] and X others" = +1. 
                            # If "Liked by [User], [User2] and X others" = +2.
                            named_users = txt.split('and')[0].replace('Liked by', '').split(',')
                            bonus = len([u for u in named_users if u.strip()])
                            dom_likes = str(count + bonus)
                        elif "others" not in txt.lower():
                            # "Liked by User1 and User2"
                            named = txt.replace('Liked by', '').split('and')
                            dom_likes = str(len([n for n in named if n.strip()]))

                # Comments: "View all X comments" is the holy grail of DOM comment counts
                view_all = container.locator('xpath=.//*[contains(text(), "View all") and contains(text(), "comment")]').first
                if view_all.is_visible(timeout=500):
                    m = re.search(r'([\d,\.km]+)', view_all.inner_text())
                    if m: dom_comments = str(parse_count(m.group(1)))
                
                # Comments: Action button aria-label
                if not dom_comments:
                    cmt_btn = container.locator('button:has(svg[aria-label="Comment"])').first
                    if cmt_btn.is_visible(timeout=500):
                        label = (cmt_btn.get_attribute("aria-label") or "").lower()
                        m = re.search(r'([\d,\.km]+)\s+comments?', label)
                        if m: dom_comments = str(parse_count(m.group(1)))

                # Views: Reels plays/views
                if is_reel or not dom_views:
                    view_loc = container.locator('xpath=.//*[contains(text(), "views") or contains(text(), "plays")]').first
                    if view_loc.is_visible(timeout=500):
                        m = re.search(r'([\d,\.km]+)', view_loc.inner_text())
                        if m: dom_views = str(parse_count(m.group(1)))

                # Reposts/Shares: look for share/send button aria-labels
                if not dom_reposts:
                    share_btn = container.locator('button:has(svg[aria-label="Share"]), button:has(svg[aria-label="Send"])').first
                    if share_btn.is_visible(timeout=500):
                        label = (share_btn.get_attribute("aria-label") or "").lower()
                        m = re.search(r'([\d,\.km]+)\s+(?:share|repost|send)', label)
                        if m: dom_reposts = str(parse_count(m.group(1)))

                # Saves: look for save button aria-labels
                if not dom_saves:
                    save_btn = container.locator('button:has(svg[aria-label="Save"]), button:has(svg[aria-label="Remove"])').first
                    if save_btn.is_visible(timeout=500):
                        label = (save_btn.get_attribute("aria-label") or "").lower()
                        m = re.search(r'([\d,\.km]+)\s+(?:save|bookmark)', label)
                        if m: dom_saves = str(parse_count(m.group(1)))

            except: pass

            # 3. Final Reconciliation
            likes = json_like or dom_likes or ""
            comments = json_comment or dom_comments or ""
            
            # Views priority: 
            # 1. Network Sniffer/JSON (most accurate raw data)
            # 2. Grid-tab cache (reliable view counts from profile/reels tab)
            # 3. DOM extraction (last resort from modal text)
            views = json_view or ""
            if not views and grid_views:
                # Try multiple lookups in the grid cache
                clean_href = href.split('?')[0].rstrip('/') + '/'
                views = grid_views.get(sc) or grid_views.get(href) or grid_views.get(clean_href) or ""
            
            if not views:
                views = dom_views or ""

            reposts = json_repost or dom_reposts or ""
            saves = json_save or dom_saves or ""

            # Check grid metrics for likes/comments if still missing
            if (not likes or likes == "N/A") and grid_metrics:
                clean_href = href.split('?')[0].rstrip('/') + '/'
                m = grid_metrics.get(sc) or grid_metrics.get(href) or grid_metrics.get(clean_href) or {}
                if m.get("likes"): likes = m["likes"]
                if m.get("comments"): comments = m["comments"]

            # Final Meta Fallback
            if not likes or likes == "N/A" or not comments or comments == "N/A":
                try:
                    desc_meta = page.locator('meta[property="og:description"]').get_attribute("content", timeout=200)
                    if desc_meta:
                        if not likes:
                            m = re.search(r'([\d,\.km]+)\s*likes?', desc_meta, re.I)
                            if m: likes = str(parse_count(m.group(1)))
                        if not comments:
                            m = re.search(r'([\d,\.km]+)\s*comments?', desc_meta, re.I)
                            if m: comments = str(parse_count(m.group(1)))
                except: pass

        except Exception:
            pass

        # Cleanup
        likes = likes if (likes and likes != "0") else "N/A"
        comments = comments if (comments and comments != "0") else "N/A"
        views = views if (views and views != "0") else ""
        reposts = reposts if (reposts and reposts != "0") else "N/A"
        saves = saves if (saves and saves != "0") else "N/A"

        # ── Display image URL ──
        # Priority: 1) Network sniffer cache  2) JSON from page  3) video poster  4) og:image  5) DOM img
        cached = self._media_cache.get(sc, {})

        # Source 1: Network sniffer / JSON extraction (highest quality)
        if cached.get("display_url"):
            display_url = cached["display_url"]
        elif json_display_url:
            display_url = json_display_url

        # Source 2: Video poster attribute (great for reels)
        if not display_url:
            try:
                vid_el = container.locator("video").first
                if vid_el.is_visible(timeout=500):
                    poster = vid_el.get_attribute("poster") or ""
                    if poster and poster.startswith("http"):
                        display_url = poster
            except Exception:
                pass

        # Source 3: og:image meta tag
        if not display_url:
            try:
                og_img = page.evaluate(
                    'document.querySelector(\'meta[property="og:image"]\')?.content || ""'
                )
                if og_img and og_img.startswith("http") and "profile_pic" not in og_img:
                    display_url = og_img
            except Exception:
                pass

        # Source 4: DOM img elements (last resort — filter aggressively)
        if not display_url:
            try:
                img_cands = container.locator("img").all()
                for cand in img_cands:
                    src = cand.get_attribute("src") or ""
                    alt = (cand.get_attribute("alt") or "").lower()
                    src_lower = src.lower()
                    # Skip profile pictures — check both alt text AND url patterns
                    if not src:
                        continue
                    if "profile picture" in alt or "profile_pic" in src_lower:
                        continue
                    if "anonymous_profile_pic" in src_lower:
                        continue
                    # Skip tiny avatars (s150x150, s100x100)
                    if re.search(r's\d{2,3}x\d{2,3}', src_lower) and "t51.2885-19" in src_lower:
                        continue
                    display_url = src
                    break
            except Exception:
                pass

        # ── Video URL ──
        # Priority: 1) Network sniffer  2) JSON from page  3) DOM (skip blob: URLs)
        if cached.get("video_url"):
            video_url = cached["video_url"]
        elif json_video_url:
            video_url = json_video_url
        else:
            try:
                vid = container.locator("video").first
                if vid.is_visible(timeout=500):
                    src = vid.get_attribute("src") or ""
                    # Only use real HTTP URLs, NOT blob: URLs (those can't be downloaded)
                    if src.startswith("http"):
                        video_url = src
            except Exception:
                pass

        # ── Carousel detection & multi-image extraction ──
        try:
            dots = container.locator('[role="tablist"] [role="tab"]').all()
            if dots: carousel_count = len(dots)
        except Exception:
            pass

        # Collect carousel URLs from network sniffer cache first
        cached_carousel = self._media_cache.get(sc, {})
        if cached_carousel.get("carousel_urls"):
            carousel_urls_list = cached_carousel["carousel_urls"].split(" | ")

        # If sniffer didn't capture carousel URLs, try JSON script tags
        if not carousel_urls_list and carousel_count > 1:
            try:
                scripts = page.locator('script[type="application/json"]').all_inner_texts()
                for content in scripts:
                    if sc in content:
                        try:
                            if len(content) < 50:
                                continue
                            j_data = json.loads(content)

                            def find_carousel_node(o, target_sc):
                                if isinstance(o, dict):
                                    if (o.get("shortcode") == target_sc or o.get("code") == target_sc):
                                        return o
                                    for v in o.values():
                                        r = find_carousel_node(v, target_sc)
                                        if r:
                                            return r
                                elif isinstance(o, list):
                                    for item in o:
                                        r = find_carousel_node(item, target_sc)
                                        if r:
                                            return r
                                return None

                            node = find_carousel_node(j_data, sc)
                            if node:
                                children = node.get("edge_sidecar_to_children") or node.get("carousel_media")
                                if isinstance(children, dict):
                                    for edge in children.get("edges", []):
                                        child = edge.get("node", {}) if isinstance(edge, dict) else {}
                                        vu = child.get("video_url")
                                        if not vu:
                                            vv = child.get("video_versions")
                                            if isinstance(vv, list) and vv:
                                                vu = vv[0].get("url")
                                        if vu and not vu.startswith("blob:"):
                                            carousel_urls_list.append(vu)
                                        else:
                                            img = child.get("display_url") or child.get("thumbnail_src")
                                            if not img:
                                                iv = child.get("image_versions2", {}).get("candidates")
                                                if isinstance(iv, list) and iv:
                                                    img = iv[0].get("url")
                                            if img:
                                                carousel_urls_list.append(img)
                                elif isinstance(children, list):
                                    for child in children:
                                        if not isinstance(child, dict):
                                            continue
                                        vu = child.get("video_url")
                                        if not vu:
                                            vv = child.get("video_versions")
                                            if isinstance(vv, list) and vv:
                                                vu = vv[0].get("url")
                                        if vu and not vu.startswith("blob:"):
                                            carousel_urls_list.append(vu)
                                        else:
                                            img = child.get("display_url") or child.get("thumbnail_src")
                                            if not img:
                                                iv = child.get("image_versions2", {}).get("candidates")
                                                if isinstance(iv, list) and iv:
                                                    img = iv[0].get("url")
                                            if img:
                                                carousel_urls_list.append(img)
                            if carousel_urls_list:
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        # Last resort: navigate through carousel slides in the DOM
        if not carousel_urls_list and carousel_count > 1:
            try:
                seen_srcs = set()
                # Collect the current visible image first
                first_img = self._get_carousel_visible_image(container)
                if first_img:
                    seen_srcs.add(first_img)
                    carousel_urls_list.append(first_img)

                # Click "Next" arrow to cycle through all slides
                for _ in range(carousel_count - 1):
                    next_btn = container.locator('button[aria-label="Next"], button[aria-label="Go forward"]').first
                    if next_btn.is_visible(timeout=800):
                        next_btn.click(timeout=1500)
                        self._human_delay(600, 1200)
                        img_url = self._get_carousel_visible_image(container)
                        if img_url and img_url not in seen_srcs:
                            seen_srcs.add(img_url)
                            carousel_urls_list.append(img_url)
                    else:
                        break
            except Exception:
                pass

        carousel_urls_str = " | ".join(carousel_urls_list) if carousel_urls_list else ""

        # Media type
        if is_reel: media_type = "Reel"
        elif carousel_count > 1: media_type = "Carousel"
        elif video_url: media_type = "Video"
        else: media_type = "Photo"

        res.update({
            "media_type": media_type,
            "caption": caption.replace("\n", " | "),
            "hashtags": extract_hashtags(caption),
            "keywords": extract_keywords(caption),
            "mentions": extract_mentions(caption),
            "tagged_users": tagged_users_count,
            "likes_count": likes,
            "comments_count": comments,
            "views_count": views,
            "reposts_count": reposts,
            "saves_count": saves,
            "is_pinned": pinned,
            "is_sponsored": sponsored,
            "timestamp": timestamp_iso,
            "date": date_str,
            "location_id": location_id,
            "audio_title": audio_title,
            "display_url": display_url,
            "video_url": video_url,
            "carousel_count": carousel_count,
            "carousel_urls": carousel_urls_str,
        })
        return res

    # ══════════════════════════════════════════════════════════════
    #  CAROUSEL HELPER
    # ══════════════════════════════════════════════════════════════

    def _get_carousel_visible_image(self, container) -> str:
        """
        Extract the currently visible image or video URL from a carousel slide.
        Filters out profile pictures and tiny avatars.
        """
        # Try video first
        try:
            vid = container.locator("video").first
            if vid.is_visible(timeout=400):
                poster = vid.get_attribute("poster") or ""
                if poster and poster.startswith("http"):
                    return poster
                src = vid.get_attribute("src") or ""
                if src.startswith("http"):
                    return src
        except Exception:
            pass

        # Then try images
        try:
            imgs = container.locator("img").all()
            for img in imgs:
                src = img.get_attribute("src") or ""
                alt = (img.get_attribute("alt") or "").lower()
                if not src or not src.startswith("http"):
                    continue
                if "profile picture" in alt or "profile_pic" in src.lower():
                    continue
                if "anonymous_profile_pic" in src.lower():
                    continue
                # Skip tiny avatars
                if re.search(r's\d{2,3}x\d{2,3}', src.lower()) and "t51.2885-19" in src.lower():
                    continue
                return src
        except Exception:
            pass

        return ""

    # ══════════════════════════════════════════════════════════════
    #  HASHTAG SCRAPING
    # ══════════════════════════════════════════════════════════════

    def scrape_hashtag(self, hashtag: str, limit: int = 20) -> list[dict]:
        """
        Navigate to ``/explore/tags/<hashtag>/`` and collect post URLs
        from the grid, then optionally scrape each post.
        """
        page = self._page
        tag = hashtag.lstrip("#")
        url = f"https://www.instagram.com/explore/tags/{tag}/"
        self.log(f"#️⃣  Scraping hashtag #{tag} (limit={limit})")
        self._navigate(url)

        # Collect post links from the grid
        post_links = set()
        scroll_count = 0

        while len(post_links) < limit and scroll_count < 15:
            anchors = page.locator('a[href*="/p/"], a[href*="/reel/"]').all()
            for a in anchors:
                href = a.get_attribute("href") or ""
                if href and ("/p/" in href or "/reel/" in href):
                    if not href.startswith("http"):
                        href = "https://www.instagram.com" + href
                    post_links.add(href)

            if len(post_links) >= limit:
                break

            page.mouse.wheel(0, 800)
            self._human_delay(2000, 4000)
            scroll_count += 1

        # Return just the URLs as simple dicts
        results = []
        for link in list(post_links)[:limit]:
            results.append({
                "url": link,
                "short_code": extract_shortcode(link),
                "source_hashtag": tag,
            })

        self.log(f"✅ Found {len(results)} posts for #{tag}.")
        return results
