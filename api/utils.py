"""
Utility helpers used across the API and scraper.
Kept in one place so every module shares the same logic.
"""

from __future__ import annotations

import re


# ─────────────────────────────────────────────
# Number parsing  (e.g. "1.2K" → 1200)
# ─────────────────────────────────────────────

def parse_count(text: str) -> int:
    """Turn Instagram-style counts ('1.2K', '3M', '10,234') into plain ints."""
    if not text:
        return 0
    text = str(text).lower().replace(",", "").strip()
    multiplier = 1
    if "k" in text:
        multiplier = 1_000
        text = text.replace("k", "")
    elif "m" in text:
        multiplier = 1_000_000
        text = text.replace("m", "")
    elif "b" in text:
        multiplier = 1_000_000_000
        text = text.replace("b", "")
    try:
        return int(float(text) * multiplier)
    except Exception:
        return 0


# ─────────────────────────────────────────────
# URL / username helpers
# ─────────────────────────────────────────────

def extract_username(url: str) -> str:
    """Pull the username out of any Instagram URL or plain handle."""
    if not url: return ""
    # Strip query parameters and trailing slashes
    clean_url = url.split('?')[0].strip().rstrip("/")
    parts = [p for p in clean_url.split("/") if p]
    if not parts: return ""
    
    # If the last part is 'p' or 'reel', try the one before it (for old style URLs)
    # but usually for profile URLs it's just the last part.
    last = parts[-1].lstrip("@")
    if last in ["p", "reel", "stories"] and len(parts) > 1:
        return parts[-2]
    return last


def normalize_url(text: str) -> str:
    """
    Accept a URL *or* a bare username / @handle and return a full
    ``https://www.instagram.com/<username>/`` URL.

    Strips Instagram tracking query params (``igsh``, ``utm_*``, etc.)
    so the browser receives a clean URL.
    """
    text = text.strip()
    if not text:
        return ""
        
    # Strip query parameters — they are tracking params and break navigation
    clean = text.split("?")[0].split("#")[0]

    if not clean.startswith("http"):
        username = clean.lstrip("@").strip("/")
        return f"https://www.instagram.com/{username}/"

    if not clean.endswith("/"):
        clean += "/"
    return clean


def extract_shortcode(url: str) -> str:
    """Get the shortcode from a post or reel URL."""
    m = re.search(r"/(p|reel)/([^/?]+)", url)
    return m.group(2) if m else ""


# ─────────────────────────────────────────────
# Caption text analysis
# ─────────────────────────────────────────────

def extract_hashtags(text: str) -> list[str]:
    """Return all #hashtags found in *text*."""
    return re.findall(r"#(\w+)", text)


def extract_mentions(text: str) -> list[str]:
    """Return all @mentions found in *text*."""
    return re.findall(r"@(\w+)", text)


def format_number(n) -> str:
    """Pretty-print a number: 1234 → '1.2K', 1000 → '1K', 1.2M, etc."""
    try:
        n = float(n)
    except (ValueError, TypeError):
        return str(n)
        
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}".rstrip('0').rstrip('.') + "M"
    if n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}".rstrip('0').rstrip('.') + "K"
    return f"{int(n):,}"


def extract_keywords(text: str) -> str:
    """Return a comma separated string of keywords extracted from caption."""
    if not text:
        return ""
    
    # Simple stop words list
    stop_words = set(["the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "it", "this", "that", "there", "i", "you", "he", "she", "we", "they", "my", "your", "his", "her", "our", "their", "so", "as", "if", "then", "just", "like", "about", "from", "when", "what", "where", "how", "why", "can", "will"])
    
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    keywords = []
    seen = set()
    for w in words:
        if w not in stop_words and w not in seen:
            keywords.append(w)
            seen.add(w)
            if len(keywords) >= 15: # limit to max 15 keywords to match behavior in screenshot
                break
                
    return ",".join(keywords)
