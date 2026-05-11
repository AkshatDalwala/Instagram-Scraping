"""
Pydantic models shared between the FastAPI server and the Streamlit frontend.
Every field has a sensible default so partial data never causes errors.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


# ─────────────────────────────────────────────
# Request models  (Streamlit → FastAPI)
# ─────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    """What the frontend sends to kick off a scraping task."""
    urls: list[str] = Field(..., description="Instagram URLs or usernames")
    media_limit: int = Field(50, ge=-1, le=1000000, description="Posts/reels per account (0 or -1 for special cases)")
    media_skip: int = Field(0, ge=0, description="Number of posts to skip before starting")
    headless: bool = Field(False, description="Run browser without visible window")
    anonymous: bool = Field(False, description="Scrape without login (fresh profile, no cookies)")
    proxy: Optional[str] = Field(None, description="Proxy URL e.g. http://host:port or socks5://user:pass@host:port")


# ─────────────────────────────────────────────
# Data models  (scraper output)
# ─────────────────────────────────────────────

class ProfileData(BaseModel):
    """All metadata we can extract from an Instagram profile page."""
    # Identity
    username: str = ""
    full_name: str = ""
    profile_pic_url: str = ""
    profile_pic_url_hd: str = ""
    biography: str = ""
    pronouns: str = ""

    # Business / status
    is_business_account: bool = False
    is_verified: bool = False
    is_private: bool = False

    # Stats
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    highlights_count: int = 0

    # Links
    external_url: str = ""
    threads_url: str = ""
    profile_url: str = ""

    # About (from 3-dot menu)
    date_joined: str = ""
    based_in: str = ""
    former_usernames: str = ""

    # Extra
    ads_enabled: bool = False
    highlights: list[str] = Field(default_factory=list)
    latest_post_url: str = ""


class MediaData(BaseModel):
    """Data for a single post, reel, or carousel item."""
    short_code: str = ""
    media_type: str = ""            # "Photo", "Video", "Carousel", "Reel"
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    keywords: str = ""
    mentions: list[str] = Field(default_factory=list)
    tagged_users: int = 0

    likes_count: str = "N/A"
    comments_count: str = "N/A"
    views_count: str = "N/A"
    reposts_count: str = "N/A"
    saves_count: str = "N/A"

    is_pinned: bool = False
    is_sponsored: bool = False
    ads_enabled: bool = False

    timestamp: str = ""
    date: str = ""

    location_id: str = ""
    audio_title: str = ""

    display_url: str = ""           # Thumbnail / poster image
    video_url: str = ""             # Direct video source URL
    carousel_count: int = 0
    carousel_urls: str = ""          # Pipe-delimited URLs of all carousel images/videos

    owner_username: str = ""


# ─────────────────────────────────────────────
# Task / response models
# ─────────────────────────────────────────────

class TaskStatus(BaseModel):
    """Returned by GET /api/tasks/{id} so the frontend knows what's happening."""
    task_id: str = ""
    status: str = "pending"         # pending | running | completed | failed
    progress: float = 0.0           # 0.0 → 1.0
    current_label: str = ""         # e.g. "Scraping @natgeo (2/5)"
    logs: list[str] = Field(default_factory=list)
    error: Optional[str] = None

    # Results (populated when status == "completed")
    profiles: list[dict] = Field(default_factory=list)
    media: list[dict] = Field(default_factory=list)
    duration_minutes: float = 0.0
