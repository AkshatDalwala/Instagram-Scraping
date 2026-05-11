"""
Instagram Scraper Pro — Streamlit Frontend
Talks to the FastAPI backend via HTTP (httpx).
"""

import streamlit as st
import pandas as pd
import httpx
import os
import json
import io
import time as _time
from datetime import datetime

# ─── Must be the very first Streamlit call ───
st.set_page_config(
    page_title="Instagram Scraper Pro",
    page_icon="📸",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Config ───
API_BASE = "http://localhost:8000"


# =====================================================================
# CUSTOM CSS
# =====================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, .stApp { font-family: 'Inter', sans-serif !important; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] {
    background: linear-gradient(135deg, #0f0f23, #1a1a2e) !important;
    border-bottom: 1px solid rgba(139,92,246,0.15);
}

/* Hero */
.hero {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 30%, #f093fb 70%, #ec4899 100%);
    border-radius: 16px; padding: 2.2rem 2rem; margin-bottom: 1.8rem;
    position: relative; overflow: hidden;
    box-shadow: 0 8px 32px rgba(139,92,246,0.25);
}
.hero::before {
    content:''; position:absolute; top:-50%; left:-50%; width:200%; height:200%;
    background: radial-gradient(circle, rgba(255,255,255,0.08) 0%, transparent 70%);
    animation: shimmer 8s ease-in-out infinite;
}
@keyframes shimmer { 0%,100%{transform:translate(0,0)} 50%{transform:translate(30px,20px)} }
.hero h1 { color:#fff; font-size:2.1rem; font-weight:800; margin:0 0 .3rem 0;
    position:relative; text-shadow:0 2px 10px rgba(0,0,0,.2); }
.hero p  { color:rgba(255,255,255,.88); font-size:1rem; margin:0; position:relative; }

/* Metric cards */
.metrics { display:flex; gap:1rem; margin-bottom:1.5rem; flex-wrap:wrap; }
.mcard {
    flex:1; min-width:130px;
    background: linear-gradient(145deg, #1e1e3a, #16213e);
    border:1px solid rgba(139,92,246,.18); border-radius:14px;
    padding:1.2rem; text-align:center;
    transition: all .3s ease; box-shadow:0 4px 15px rgba(0,0,0,.2);
}
.mcard:hover { transform:translateY(-3px); border-color:rgba(139,92,246,.45); }
.mcard .icon { font-size:1.5rem; margin-bottom:.3rem; }
.mcard .val  { font-size:1.7rem; font-weight:700;
    background:linear-gradient(135deg,#8b5cf6,#ec4899);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.mcard .lbl  { font-size:.72rem; color:#94a3b8; text-transform:uppercase;
    letter-spacing:.8px; margin-top:.2rem; font-weight:500; }

/* Section headers */
.sec-h { display:flex; align-items:center; gap:.5rem; margin:1.5rem 0 .8rem;
    padding-bottom:.5rem; border-bottom:2px solid rgba(139,92,246,.2); }
.sec-h h3 { margin:0; font-weight:600; color:#e2e8f0; font-size:1.1rem; }

/* Badges */
.badge { display:inline-flex; align-items:center; gap:.35rem;
    padding:.25rem .75rem; border-radius:50px; font-size:.75rem; font-weight:600; }
.badge-ok  { background:rgba(34,197,94,.12); color:#22c55e; border:1px solid rgba(34,197,94,.25); }
.badge-run { background:rgba(234,179,8,.12);  color:#eab308; border:1px solid rgba(234,179,8,.25);
    animation: pulse 2s ease-in-out infinite; }
.badge-no  { background:rgba(239,68,68,.12);  color:#ef4444; border:1px solid rgba(239,68,68,.25); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.65} }

/* Log box */
.logbox {
    background:#0c0c1d; border:1px solid rgba(139,92,246,.12); border-radius:10px;
    padding:1rem; font-family:'JetBrains Mono','Fira Code',monospace;
    font-size:.8rem; color:#94a3b8; max-height:300px; overflow-y:auto; line-height:1.7;
}
.logbox .ll { padding:2px 0; border-bottom:1px solid rgba(255,255,255,.03); }

/* Divider */
.divider {
    height:2px; border:none; margin:1.5rem 0; border-radius:2px;
    background:linear-gradient(90deg, transparent, #8b5cf6, #ec4899, #8b5cf6, transparent);
    background-size:200% 100%; animation: gflow 4s linear infinite;
}
@keyframes gflow { 0%{background-position:0% 0%} 100%{background-position:200% 0%} }

/* Buttons */
.stButton > button {
    background:linear-gradient(135deg,#8b5cf6,#7c3aed) !important;
    border:none !important; color:#fff !important; font-weight:600 !important;
    padding:.6rem 1.8rem !important; border-radius:10px !important;
    box-shadow:0 4px 15px rgba(139,92,246,.3) !important;
}
.stButton > button:hover { transform:translateY(-2px) !important;
    box-shadow:0 6px 20px rgba(139,92,246,.45) !important; }
.stDownloadButton > button {
    background:linear-gradient(135deg,#1e1e3a,#16213e) !important;
    border:1px solid rgba(139,92,246,.3) !important; color:#a78bfa !important;
    border-radius:10px !important; }
.stDownloadButton > button:hover { border-color:#8b5cf6 !important; }

/* Inputs */
.stTextArea textarea, .stTextInput input {
    background:#0c0c1d !important; border:1px solid rgba(139,92,246,.2) !important;
    border-radius:10px !important; color:#e2e8f0 !important; }
.stTextArea textarea:focus, .stTextInput input:focus {
    border-color:#8b5cf6 !important; box-shadow:0 0 0 2px rgba(139,92,246,.15) !important; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background:linear-gradient(180deg,#0f0f23,#151530) !important;
    border-right:1px solid rgba(139,92,246,.12); }
section[data-testid="stSidebar"] .stMarkdown h2 {
    font-size:.95rem; text-transform:uppercase; letter-spacing:1.5px; color:#8b5cf6; margin-top:1.3rem; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap:.5rem; }
.stTabs [data-baseweb="tab"] { background:rgba(139,92,246,.06); border-radius:8px;
    padding:.5rem 1rem; color:#94a3b8; border:1px solid transparent; font-weight:500; }
.stTabs [aria-selected="true"] { background:rgba(139,92,246,.15) !important;
    border-color:rgba(139,92,246,.35) !important; color:#a78bfa !important; }

::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:#0f0f23; }
::-webkit-scrollbar-thumb { background:rgba(139,92,246,.3); border-radius:3px; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# SESSION STATE
# =====================================================================
for key, default in {
    "task_id": None,
    "task_data": None,
    "polling": False,
    "accumulated_profiles": [],
    "accumulated_media": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# =====================================================================
# DATA PERSISTENCE
# =====================================================================
DATA_FILE = "scraped_data.json"

def load_accumulated_data():
    """Load profiles and media from the local JSON file."""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                st.session_state.accumulated_profiles = data.get("profiles", [])
                st.session_state.accumulated_media = data.get("media", [])
    except Exception as e:
        print(f"Error loading data: {e}")

def save_accumulated_data():
    """Save the current session's accumulated data to the local JSON file."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({
                "profiles": st.session_state.accumulated_profiles,
                "media": st.session_state.accumulated_media
            }, f, indent=2)
    except Exception as e:
        st.error(f"Error saving data: {e}")

def clear_accumulated_data():
    """Wipe session state and delete the local JSON file."""
    st.session_state.accumulated_profiles = []
    st.session_state.accumulated_media = []
    st.session_state.task_id = None
    st.session_state.task_data = None
    if os.path.exists(DATA_FILE):
        try:
            os.remove(DATA_FILE)
        except:
            pass

def merge_results(new_profiles, new_media):
    """Merge new data into accumulation with deduplication."""
    # 1. Profiles (by username)
    existing_usernames = {p.get("username") for p in st.session_state.accumulated_profiles if p.get("username")}
    for p in new_profiles:
        if p.get("username") not in existing_usernames:
            st.session_state.accumulated_profiles.append(p)
            existing_usernames.add(p.get("username"))
        else:
            # Update existing profile with potentially fresher data
            for i, ep in enumerate(st.session_state.accumulated_profiles):
                if ep.get("username") == p.get("username"):
                    st.session_state.accumulated_profiles[i] = p
                    break
    
    # 2. Media (by short_code)
    existing_codes = {m.get("short_code") for m in st.session_state.accumulated_media if m.get("short_code")}
    for m in new_media:
        if m.get("short_code") not in existing_codes:
            st.session_state.accumulated_media.append(m)
            existing_codes.add(m.get("short_code"))
        else:
            # Update existing media item
            for i, em in enumerate(st.session_state.accumulated_media):
                if em.get("short_code") == m.get("short_code"):
                    st.session_state.accumulated_media[i] = m
                    break
    
    save_accumulated_data()

# Load data on startup
if not st.session_state.accumulated_profiles and not st.session_state.accumulated_media:
    load_accumulated_data()


# =====================================================================
# HELPERS
# =====================================================================
def api_ok() -> bool:
    """Check if the FastAPI backend is reachable."""
    try:
        r = httpx.get(f"{API_BASE}/api/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def start_task(urls, media_limit, media_skip, headless, anonymous=False, proxy=None) -> str | None:
    """POST /api/scrape and return the task_id."""
    try:
        payload = {
            "urls": urls,
            "media_limit": media_limit,
            "media_skip": media_skip,
            "headless": headless,
            "anonymous": anonymous,
        }
        if proxy:
            payload["proxy"] = proxy
        r = httpx.post(
            f"{API_BASE}/api/scrape",
            json=payload,
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()["task_id"]
        st.error(f"API error: {r.text}")
    except Exception as e:
        st.error(f"Cannot reach backend: {e}")
    return None


def poll_task(task_id: str) -> dict:
    """GET /api/tasks/{id}."""
    r = httpx.get(f"{API_BASE}/api/tasks/{task_id}", timeout=10)
    return r.json()


def build_df(profiles, media) -> pd.DataFrame:
    """Merge profile + media into one DataFrame."""
    media_cols = [
        "short_code", "media_type", "caption", "hashtags", "keywords", "mentions", "tagged_users",
        "likes_count", "comments_count", "views_count", "reposts_count", "saves_count", "is_pinned",
        "is_sponsored", "timestamp", "date",
        "audio_title", "display_url",
        "owner_username",
    ]
    rows = []
    for i, p in enumerate(profiles):
        username = p.get("username", "")
        # Find media for this profile
        p_media = [m for m in media if m.get("owner_username") == username]

        if p_media:
            for m in p_media:
                row = {**p, **m}
                # Ensure new columns have defaults for old cached data
                row.setdefault("reposts_count", "N/A")
                row.setdefault("saves_count", "N/A")
                rows.append(row)
        else:
            row = dict(p)
            for c in media_cols:
                row[c] = ""
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Fill any remaining NaN in engagement columns (from old cached data)
    for col in ["reposts_count", "saves_count"]:
        if col in df.columns:
            df[col] = df[col].fillna("N/A")
    # Remove columns user does not want in final output/export.
    return df.drop(
        columns=[
            "pronouns",
            "location_id",
            "carousel_count",
            "has_reels",
            "avtar",
            "avatar",
            "profile_pic_url",
            "profile_pic_url_hd",
            "video_url",
        ],
        errors="ignore",
    ).rename(columns={
        "likes_count": "Likes",
        "comments_count": "Comments",
        "views_count": "Views",
        "reposts_count": "Reposts",
        "saves_count": "Saves",
        "followers_count": "Followers",
        "following_count": "Following",
        "posts_count": "Posts",
        "media_type": "Type",
        "full_name": "Name",
        "biography": "Bio",
        "external_url": "Website",
    }, errors="ignore")


def to_csv(df):
    return df.to_csv(index=False).encode("utf-8")

def to_json(df):
    return df.to_json(orient="records", indent=2).encode("utf-8")

def to_excel(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Instagram Data")
    return buf.getvalue()


# =====================================================================
# SIDEBAR
# =====================================================================
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    headless = st.toggle("🖥️ Headless Mode", value=False,
                         help="Hide the browser. Disable for first-time login.")
    anonymous = st.toggle("🔓 Anonymous Mode", value=False,
                          help="Scrape without login (fresh profile, no cookies). "
                               "Safer for your account but may get less data on private profiles.")
    proxy_url = st.text_input("🌐 Proxy / VPN", value="",
                              placeholder="http://host:port or socks5://user:pass@host:port",
                              help="Route traffic through a proxy. Supports HTTP, HTTPS, SOCKS5.")

    media_limit = st.number_input("📸 Media Limit", min_value=0, max_value=1_000_000, value=50,
                                   help="Posts/Reels to deep-scrape per account. Set to 0 for UNLIMITED.")
    media_skip = st.number_input("⏭️ Skip Posts", min_value=0, max_value=1_000_000, value=0,
                                  help="Number of posts to skip from the top before starting.")

    st.markdown("## Export")
    export_fmt = st.radio("Format", ["CSV", "JSON", "Excel", "All"], horizontal=True)

    st.markdown("## Backend")
    backend_up = api_ok()
    if backend_up:
        st.markdown('<span class="badge badge-ok">● API Online</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge badge-no">● API Offline</span>', unsafe_allow_html=True)
        st.caption("Start the backend: `python -m uvicorn api.server:app --port 8000`")

    # Session status
    st.markdown("## Session")
    if anonymous:
        st.markdown('<span class="badge badge-run">● Anonymous</span>', unsafe_allow_html=True)
        st.caption("Fresh profile — no login cookies used.")
    else:
        try:
            r = httpx.get(f"{API_BASE}/api/session/status", timeout=3)
            if r.json().get("session_exists"):
                st.markdown('<span class="badge badge-ok">● Session Found</span>', unsafe_allow_html=True)
                st.caption("Login cookies detected.")
            else:
                st.markdown('<span class="badge badge-run">● No Session</span>', unsafe_allow_html=True)
                st.caption("First run needs manual login.")
        except Exception:
            st.caption("Cannot check session (backend offline).")

    if proxy_url:
        st.markdown(f'<span class="badge badge-ok">● Proxy Active</span>', unsafe_allow_html=True)
        st.caption(f"`{proxy_url[:40]}{'...' if len(proxy_url) > 40 else ''}`")

    st.markdown("## About")
    st.caption("Powered by **Camoufox** 🦊 anti-detect browser + **FastAPI** + **Streamlit**. "
               "For educational & research use only.")

    if st.button("🗑️ Clear Results", use_container_width=True):
        clear_accumulated_data()
        st.rerun()


# =====================================================================
# MAIN AREA
# =====================================================================

# Hero banner
st.markdown("""
<div class="hero">
    <h1>📸 Instagram Scraper Pro</h1>
    <p>Apify-grade extraction with anti-detect stealth — Camoufox 🦊 + FastAPI + Streamlit</p>
</div>
""", unsafe_allow_html=True)

# ─── Input ───
st.markdown('<div class="sec-h"><h3>🎯 Target Accounts</h3></div>', unsafe_allow_html=True)

urls_input = st.text_area(
    "Enter Instagram URLs or usernames (one per line)",
    placeholder="https://www.instagram.com/natgeo/\n@cristiano\nviaborsa\n#travel  (hashtag scrape)",
    height=120,
    label_visibility="collapsed",
)

c1, c2, c3, _ = st.columns([1.4, 1.4, 1.4, 4])
with c1:
    btn_full = st.button("🚀 Full Scrape", use_container_width=True, type="primary")
with c2:
    btn_profile = st.button("👤 Profile Only", use_container_width=True)
with c3:
    btn_stop = st.button("⛔ (refresh)", use_container_width=True,
                         help="Refresh the page to reset the poller")

# ─── Process button clicks ───
raw = [u.strip() for u in (urls_input or "").splitlines() if u.strip()]

if (btn_full or btn_profile) and raw:
    if not backend_up:
        st.error("❌ Backend is offline. Start FastAPI first.")
    else:
        ml = media_limit if btn_full else -1
        sk = media_skip if btn_full else 0
        px = proxy_url.strip() if proxy_url and proxy_url.strip() else None
        task_id = start_task(raw, ml, sk, headless, anonymous, px)
        if task_id:
            st.session_state.task_id = task_id
            st.session_state.task_data = None
            st.rerun()
elif (btn_full or btn_profile) and not raw:
    st.error("Enter at least one URL or username.")


# =====================================================================
# POLLING LOOP  (runs when a task is active)
# =====================================================================
if st.session_state.task_id and not st.session_state.task_data:
    task_id = st.session_state.task_id

    with st.status(f"🔄 Scraping… (task {task_id})", expanded=True) as status_ui:
        progress_bar = st.progress(0, text="Starting…")
        log_area = st.empty()

        while True:
            try:
                data = poll_task(task_id)
            except Exception as e:
                st.error(f"Polling error: {e}")
                break

            # Update progress
            pct = data.get("progress", 0)
            label = data.get("current_label", "")
            progress_bar.progress(min(pct, 1.0), text=label)

            # Update logs
            logs = data.get("logs", [])
            if logs:
                log_html = "\n".join(f'<div class="ll">{l}</div>' for l in logs[-30:])
                log_area.markdown(f'<div class="logbox">{log_html}</div>', unsafe_allow_html=True)

            # Check completion
            if data["status"] in ("completed", "failed"):
                st.session_state.task_data = data
                if data["status"] == "completed":
                    status_ui.update(label="✅ Scraping complete!", state="complete", expanded=False)
                    # Merge results into accumulated storage
                    merge_results(data.get("profiles", []), data.get("media", []))
                else:
                    err_msg = data.get('error','')
                    status_ui.update(label=f"❌ Failed: {err_msg}", state="error")
                    st.error(f"**Scraping failed:** {err_msg}")
                    if "disable headless" in err_msg.lower():
                        st.info("💡 **Tip:** Turn off 'Headless Mode' in the sidebar and try again to log in manually.")
                break

            _time.sleep(2)  # Poll every 2 seconds


# =====================================================================
# RESULTS
# =====================================================================
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ─── Use accumulated data if available, otherwise fallback to last task ───
task_data = st.session_state.task_data
profiles = st.session_state.accumulated_profiles
media = st.session_state.accumulated_media

# Determine if we have anything to show
has_results = len(profiles) > 0 or len(media) > 0

if has_results:
    duration = task_data.get("duration_minutes", 0) if task_data else 0

    # Metrics row
    st.markdown(f"""
    <div class="metrics">
        <div class="mcard"><div class="icon">👤</div><div class="val">{len(profiles)}</div><div class="lbl">Profiles</div></div>
        <div class="mcard"><div class="icon">📸</div><div class="val">{len(media)}</div><div class="lbl">Media</div></div>
        <div class="mcard"><div class="icon">⏱️</div><div class="val">{duration:.2f}m</div><div class="lbl">Duration</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Output folder info
    usernames = [p.get("username", "?") for p in profiles]
    output_dirs = [f"output/{u}/" for u in usernames if u != "?"]
    if output_dirs:
        dirs_str = ", ".join([f"<code>{d}</code>" for d in output_dirs[:5]])
        st.markdown(f'''
        <div style="background: rgba(34,197,94,.08); border: 1px solid rgba(34,197,94,.25);
                    border-radius: 10px; padding: 0.8rem 1.2rem; margin-bottom: 1.2rem;
                    display: flex; align-items: center; gap: 0.6rem;">
            <span style="font-size: 1.3rem;">📁</span>
            <div>
                <span style="color: #22c55e; font-weight: 600; font-size: 0.85rem;">Output saved to:</span>
                <span style="color: #94a3b8; font-size: 0.82rem; margin-left: 0.4rem;">{dirs_str}</span>
                <br><span style="color: #64748b; font-size: 0.72rem;">csv/ • images/&lt;date&gt;/ • videos/&lt;date&gt;/</span>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    # Tabs
    tab_all, tab_profiles, tab_media, tab_logs = st.tabs([
        "📊 All Data", "👤 Profiles", "📸 Media", "📋 Logs"
    ])

    with tab_all:
        st.markdown('<div class="sec-h"><h3>📊 Combined Data</h3></div>', unsafe_allow_html=True)
        df = build_df(profiles, media)
        if not df.empty:
            st.dataframe(df, width=1200, height=420,
                         column_config={
                             "profile_url": st.column_config.LinkColumn("Profile", width="medium"),
                             "display_url": st.column_config.ImageColumn("Thumb", width="small"),
                             "Followers": st.column_config.NumberColumn("Followers", format="%d"),
                             "Following": st.column_config.NumberColumn("Following", format="%d"),
                             "Posts": st.column_config.NumberColumn("Posts", format="%d"),
                         })

            # Export
            st.markdown('<div class="sec-h"><h3>📥 Export</h3></div>', unsafe_allow_html=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            e1, e2, e3, _ = st.columns([1, 1, 1, 4])
            with e1:
                if export_fmt in ("CSV", "All"):
                    st.download_button("⬇ CSV", to_csv(df), f"insta_{ts}.csv", "text/csv", use_container_width=True)
            with e2:
                if export_fmt in ("JSON", "All"):
                    st.download_button("⬇ JSON", to_json(df), f"insta_{ts}.json", "application/json", use_container_width=True)
            with e3:
                if export_fmt in ("Excel", "All"):
                    st.download_button("⬇ Excel", to_excel(df), f"insta_{ts}.xlsx",
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)

    with tab_profiles:
        st.markdown('<div class="sec-h"><h3>👤 Profile Details</h3></div>', unsafe_allow_html=True)
        for p in profiles:
            u = p.get("username", "?")
            f_cnt = p.get("followers_count", 0)
            v = "✅" if p.get("is_verified") else ""
            with st.expander(f"@{u} {v}  —  {f_cnt:,} followers", expanded=len(profiles) == 1):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Followers", f"{f_cnt:,}")
                c2.metric("Following", f"{p.get('following_count', 0):,}")
                c3.metric("Posts", f"{p.get('posts_count', 0):,}")
                st.markdown(f"**Bio:** {p.get('biography', '—')}")
                st.markdown(f"**Joined:** {p.get('date_joined', '—')}  ·  **Based in:** {p.get('based_in', '—')}")
                if p.get("highlights"):
                    st.markdown(f"**Highlights:** {', '.join(p['highlights'])}")
                if p.get("external_url"):
                    st.markdown(f"**Links:** {p['external_url']}")
                if p.get("threads_url"):
                    st.markdown(f"**Threads:** {p['threads_url']}")
                if p.get("former_usernames"):
                    st.markdown(f"**Former usernames:** {p['former_usernames']}")

    with tab_media:
        if media:
            total_outputs = len(media)
            posts_count = sum(1 for m in media if str(m.get("media_type")).lower() != "reel")
            reels_count = sum(1 for m in media if str(m.get("media_type")).lower() == "reel")
            st.markdown('<div class="sec-h"><h3>All Captured Outputs</h3></div>', unsafe_allow_html=True)
            st.caption(f"Total outputs: {total_outputs} | Posts: {posts_count} | Reels: {reels_count}")
            
            for m in media:
                st.markdown(f"**{'Posts' if str(m.get('media_type')).lower() != 'reel' else 'Reels'}**")
                with st.container(border=True):
                    mt = str(m.get("media_type")).lower()
                    if mt == "photo":
                        mt = "image_post"
                    
                    st.markdown(f'''
                        <div style="margin-bottom:10px;">
                            <span class="badge" style="border: 1px solid rgba(139,92,246,.3); background: rgba(139,92,246,.1); color: #c4b5fd; margin-right: 5px; padding: 2px 10px;">Post</span>
                            <span class="badge" style="border: 1px solid rgba(139,92,246,.3); background: rgba(139,92,246,.1); color: #c4b5fd; margin-right: 5px; padding: 2px 10px;">{mt}</span>
                            <span class="badge" style="border: 1px solid rgba(139,92,246,.3); background: rgba(139,92,246,.1); color: #c4b5fd; padding: 2px 10px;">{'posts' if mt != 'reel' else 'reels'}</span>
                        </div>
                    ''', unsafe_allow_html=True)
                    
                    if m.get('display_url'):
                        st.image(m['display_url'], use_container_width=True)
                    
                    table_data = {
                        "Likes": m.get("likes_count", "0"),
                        "Comments": m.get("comments_count", "0"),
                        "Views": m.get("views_count", "0") if m.get("views_count") else "",
                        "Reposts": m.get("reposts_count") or "N/A",
                        "Saves": m.get("saves_count") or "N/A",
                        "Tagged Users": str(m.get("tagged_users", "0")),
                        "Hashtags": ",".join(m.get("hashtags", [])) if isinstance(m.get("hashtags"), list) else m.get("hashtags", ""),
                        "Keywords": m.get("keywords", ""),
                        "Mentions": ",".join(m.get("mentions", [])) if isinstance(m.get("mentions"), list) else m.get("mentions", ""),
                        "Active Ads": "✅ Active" if m.get("ads_enabled") else "❌ None",
                        "Posted At": m.get("timestamp", ""),
                        "Caption": m.get("caption", ""),
                    }
                    
                    html_rows = ""
                    for k, v in table_data.items():
                        # Protect against empty lists or none
                        val = v if v is not None and v != "" else ""
                        html_rows += f'''
                        <tr style="border-bottom: 1px solid rgba(139,92,246,.12);">
                            <td style="padding: 12px 10px; width: 140px; color: #94a3b8; font-weight: 500; font-size: 0.9em;">{k}</td>
                            <td style="padding: 12px 10px; color: #e2e8f0; font-size: 0.9em; word-break: break-word;">{val}</td>
                        </tr>
                        '''
                    
                    st.markdown(f'''
                    <div style="border: 1px solid rgba(139,92,246,.15); border-radius: 8px; margin-top: 15px; margin-bottom: 15px; background: rgba(15,15,35,0.4);">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tbody>
                                {html_rows}
                            </tbody>
                        </table>
                    </div>
                    ''', unsafe_allow_html=True)
                    
                    if m.get('display_url'):
                        st.markdown("**Remote media URLs:**")
                        st.markdown(f"- <a style='word-break: break-all; color: #60a5fa; font-size: 0.85em;' href='{m['display_url']}'>{m['display_url']}</a>", unsafe_allow_html=True)
        else:
            st.markdown('<div class="sec-h"><h3>All Captured Outputs</h3></div>', unsafe_allow_html=True)
            st.info("No media data. Set **Media Limit** (use 0 for UNLIMITED) in the sidebar.")

    with tab_logs:
        st.markdown('<div class="sec-h"><h3>📋 Scrape Logs</h3></div>', unsafe_allow_html=True)
        logs = task_data.get("logs", []) if task_data else []
        if logs:
            log_html = "\n".join(f'<div class="ll">{l}</div>' for l in logs)
            st.markdown(f'<div class="logbox">{log_html}</div>', unsafe_allow_html=True)
        else:
            st.info("No logs available for the current session.")

elif task_data and task_data.get("status") == "failed":
    st.error(f"Scraping failed: {task_data.get('error', 'Unknown error')}")
    logs = task_data.get("logs", [])
    if logs:
        with st.expander("View logs"):
            for l in logs:
                st.text(l)

elif not has_results:
    # Empty state
    st.markdown("""
    <div style="text-align:center; padding:3.5rem 2rem; opacity:.55;">
        <div style="font-size:3.5rem; margin-bottom:.8rem;">📸</div>
        <h3 style="color:#64748b; font-weight:500;">No data yet</h3>
        <p style="color:#475569; font-size:.92rem;">
            Enter Instagram URLs above and click <strong>🚀 Full Scrape</strong> to begin.
            <br><small>Data will accumulate here until you click <strong>Clear Results</strong>.</small>
        </p>
    </div>
    """, unsafe_allow_html=True)

# End of file
