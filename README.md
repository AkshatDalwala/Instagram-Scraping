# 📸 Instagram Scraper Pro

Apify-grade Instagram scraper built with **Camoufox** 🦊 (anti-detect browser), **FastAPI** (backend), and **Streamlit** (UI).

## Project Structure

```
├── api/
│   ├── __init__.py        # Package init
│   ├── server.py          # FastAPI — endpoints & task management
│   ├── scraper.py         # Camoufox scraper — all extraction logic
│   ├── models.py          # Pydantic — request/response schemas
│   └── utils.py           # Helpers — parse counts, URLs, hashtags
├── app.py                 # Streamlit — frontend dashboard
├── .streamlit/
│   └── config.toml        # Theme config
├── ig_session/            # Persistent browser session (auto-created)
├── requirements.txt       # Python dependencies
├── start.bat              # One-click launcher (Windows)
└── README.md
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download Camoufox browser binary (first time only)
camoufox fetch

# 3. Start both servers (Windows)
start.bat

# — OR start manually —
# Terminal 1: Backend
python -m uvicorn api.server:app --port 8000

# Terminal 2: Frontend
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

## What Gets Scraped

### Profile Data
| Field | Description |
|-------|-------------|
| `username`, `full_name` | Identity |
| `biography`, `pronouns` | Bio info |
| `category`, `is_business_account` | Business type |
| `followers_count`, `following_count`, `posts_count` | Stats |
| `is_verified`, `is_private` | Account flags |
| `external_url`, `threads_url` | Links |
| `profile_pic_url`, `profile_pic_url_hd` | Avatar URLs |
| `date_joined`, `based_in`, `former_usernames` | About info |
| `highlights`, `highlights_count` | Story highlights |
| `reels_count`, `latest_post_url` | Content info |
| `related_profiles` | Suggested accounts |

### Post / Reel Data
| Field | Description |
|-------|-------------|
| `short_code`, `url` | Identifiers |
| `media_type` | Photo / Video / Carousel / Reel |
| `caption`, `hashtags`, `keywords` | Content |
| `mentions`, `tagged_users` | People |
| `likes_count`, `comments_count`, `views_count` | Engagement |
| `is_pinned`, `is_sponsored` | Flags |
| `timestamp`, `date` | Timing |
| `location_name`, `location_id` | Location |
| `audio_title` | Reel audio |
| `display_url`, `video_url` | Media URLs |
| `alt_text`, `carousel_count` | Extras |

### Comments
| Field | Description |
|-------|-------------|
| `text`, `username` | Comment content |
| `timestamp`, `likes_count` | Metadata |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/scrape` | Start a scraping task (background) |
| `GET` | `/api/tasks/{id}` | Poll task status, logs, results |
| `GET` | `/api/tasks` | List all tasks |
| `GET` | `/api/session/status` | Check browser session |
| `GET` | `/api/health` | Health check |

## First-Time Login

1. Set **Headless Mode = OFF** in the sidebar
2. Enter any Instagram URL and click **🚀 Full Scrape**
3. The Camoufox browser will open — log in manually
4. The session is saved to `ig_session/` and persists across restarts

## Export Formats

- **CSV** — spreadsheet-ready
- **JSON** — structured data
- **Excel** — `.xlsx` with formatting

---

> ⚠️ **For educational & research use only.** Respect Instagram's Terms of Service and applicable privacy laws.
