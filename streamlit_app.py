"""
Newsletter AI - Streamlit App
社内向けメルマガ生成ツール（セキュアなチーム共有版）
"""

import os
import uuid
import sqlite3
import smtplib
import time
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

import bcrypt
import streamlit as st

from ai_service import generate_newsletter, read_file_content

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300
SESSION_TIMEOUT_MINUTES = 60
VERIFICATION_TOKEN_EXPIRE_HOURS = 24

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_CATEGORIES = {
    "products": "商品情報",
    "instructions": "指示書",
    "templates": "テンプレート",
    "decoration": "装飾テンプレート",
}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# UI Design System — Notion / Airbnb inspired
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Design Tokens ── */
:root {
    --bg:             #FAFAFA;
    --bg-subtle:      #F1F5F9;
    --card:           #FFFFFF;
    --text:           #333333;
    --text-secondary: #64748B;
    --text-muted:     #94A3B8;
    --main:           #1E293B;
    --accent:         #FB7185;
    --accent-hover:   #F43F5E;
    --accent-soft:    #FFF1F2;
    --border:         #F1F5F9;
    --border-hover:   #E2E8F0;
    --shadow-sm:      0 1px 2px rgba(0,0,0,0.04);
    --shadow-md:      0 4px 16px rgba(0,0,0,0.06);
    --shadow-lg:      0 8px 30px rgba(0,0,0,0.08);
    --radius:         14px;
    --radius-sm:      10px;
    --radius-pill:    999px;
    --transition:     all 0.2s cubic-bezier(0.4,0,0.2,1);
}

/* ── Global ── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    color: var(--text) !important;
    -webkit-font-smoothing: antialiased;
}
.main {
    background: var(--bg) !important;
}
.main .block-container {
    max-width: 920px;
    padding: 2.5rem 2rem 4rem;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: var(--main) !important;
    border-right: none !important;
}
section[data-testid="stSidebar"] * {
    color: #CBD5E1 !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] strong {
    color: #F8FAFC !important;
}
section[data-testid="stSidebar"] .stRadio > label {
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.1rem 0;
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label {
    padding: 0.5rem 0.75rem;
    border-radius: var(--radius-sm);
    transition: var(--transition);
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover {
    background: rgba(255,255,255,0.08);
}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label[data-checked="true"],
section[data-testid="stSidebar"] .stRadio [role="radiogroup"] [aria-checked="true"] {
    background: rgba(251,113,133,0.15) !important;
    color: #FB7185 !important;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.1) !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    color: #CBD5E1 !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.14) !important;
    color: #F8FAFC !important;
}

/* ── Cards ── */
.app-card {
    background: var(--card);
    border-radius: var(--radius);
    padding: 1.5rem 1.75rem;
    margin-bottom: 1.25rem;
    border: 1px solid var(--border);
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
}
.app-card:hover {
    box-shadow: var(--shadow-md);
    border-color: var(--border-hover);
}

/* ── Page headers ── */
.page-title {
    font-size: 1.875rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--main);
    margin-bottom: 0.25rem;
    line-height: 1.2;
}
.page-subtitle {
    font-size: 0.95rem;
    color: var(--text-secondary);
    font-weight: 400;
    margin-bottom: 2.5rem;
    line-height: 1.5;
}

/* ── Auth ── */
.auth-container {
    max-width: 400px;
    margin: 3rem auto;
}
.auth-logo {
    font-size: 1.75rem;
    font-weight: 700;
    text-align: center;
    letter-spacing: -0.03em;
    color: var(--main);
    margin-bottom: 0.125rem;
}
.auth-tagline {
    text-align: center;
    color: var(--text-muted);
    font-size: 0.875rem;
    font-weight: 400;
    margin-bottom: 2.5rem;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    padding: 0.625rem 1.5rem !important;
    transition: var(--transition) !important;
    border: 1px solid var(--border-hover) !important;
    background: var(--card) !important;
    color: var(--text) !important;
    box-shadow: var(--shadow-sm) !important;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-md) !important;
    border-color: #CBD5E1 !important;
}
.stButton > button:active {
    transform: translateY(0);
}
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(251,113,133,0.3) !important;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {
    background: var(--accent-hover) !important;
    box-shadow: 0 4px 16px rgba(251,113,133,0.35) !important;
}
.stFormSubmitButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    padding: 0.625rem 1.5rem !important;
    transition: var(--transition) !important;
}

/* ── Form inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--border-hover) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.9rem !important;
    padding: 0.75rem 1rem !important;
    background: var(--card) !important;
    color: var(--text) !important;
    transition: var(--transition) !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
.stTextInput > div > div > input::placeholder,
.stTextArea > div > div > textarea::placeholder {
    color: var(--text-muted) !important;
}
.stSelectbox > div > div {
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--border-hover) !important;
}
.stMultiSelect > div > div {
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--border-hover) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: var(--bg-subtle);
    border-radius: var(--radius-sm);
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    font-weight: 500;
    font-size: 0.825rem;
    padding: 0.5rem 1.125rem;
    color: var(--text-secondary);
    transition: var(--transition);
}
.stTabs [data-baseweb="tab"]:hover {
    color: var(--text);
}
.stTabs [aria-selected="true"] {
    background: var(--card) !important;
    color: var(--main) !important;
    box-shadow: var(--shadow-sm) !important;
    font-weight: 600 !important;
}

/* ── Expander ── */
.streamlit-expanderHeader {
    border-radius: var(--radius-sm) !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
    color: var(--text) !important;
    padding: 0.875rem 1rem !important;
    background: var(--bg-subtle) !important;
    border: 1px solid var(--border) !important;
    transition: var(--transition) !important;
}
.streamlit-expanderHeader:hover {
    background: var(--border) !important;
}
.streamlit-expanderContent {
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 var(--radius-sm) var(--radius-sm);
}

/* ── Stat cards ── */
.stat-row {
    display: flex;
    gap: 1.25rem;
    margin: 1.5rem 0;
}
.stat-box {
    flex: 1;
    background: var(--card);
    border-radius: var(--radius);
    padding: 1.25rem;
    text-align: center;
    border: 1px solid var(--border);
    box-shadow: var(--shadow-sm);
}
.stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--main);
    letter-spacing: -0.02em;
}
.stat-label {
    font-size: 0.7rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.25rem;
}

/* ── Badges ── */
.badge-ok {
    display: inline-block;
    background: #ECFDF5;
    color: #059669;
    padding: 3px 12px;
    border-radius: var(--radius-pill);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.badge-pending {
    display: inline-block;
    background: #FFF7ED;
    color: #EA580C;
    padding: 3px 12px;
    border-radius: var(--radius-pill);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.badge-info {
    display: inline-block;
    background: var(--accent-soft);
    color: var(--accent);
    padding: 3px 12px;
    border-radius: var(--radius-pill);
    font-size: 0.7rem;
    font-weight: 600;
}

/* ── Alerts ── */
.stAlert > div {
    border-radius: var(--radius-sm) !important;
    border: none !important;
    font-size: 0.875rem;
}

/* ── Dividers ── */
hr {
    border: none !important;
    border-top: 1px solid var(--border) !important;
    margin: 2rem 0 !important;
}

/* ── Download button ── */
.stDownloadButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 500 !important;
    border: 1px solid var(--border-hover) !important;
    background: var(--card) !important;
    transition: var(--transition) !important;
}
.stDownloadButton > button:hover {
    background: var(--bg-subtle) !important;
    border-color: #CBD5E1 !important;
}

/* ── Checkbox / Radio ── */
.stCheckbox label span,
.stRadio label span {
    font-size: 0.875rem !important;
}

/* ── File uploader ── */
.stFileUploader > div {
    border-radius: var(--radius-sm) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: #CBD5E1;
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: #94A3B8;
}

/* ── Hide Streamlit chrome ── */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.environ.get(key, default)


def get_allowed_domains() -> list[str]:
    raw = get_secret("ALLOWED_EMAIL_DOMAINS", "androots.co.jp")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _domains_display() -> str:
    return " / ".join(f"@{d}" for d in get_allowed_domains())


def validate_email_domain(email: str) -> bool:
    email = email.strip().lower()
    return any(email.endswith(f"@{d}") for d in get_allowed_domains())


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_token TEXT,
            token_created_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
    for col, definition in [
        ("email", "TEXT DEFAULT ''"),
        ("is_verified", "INTEGER NOT NULL DEFAULT 0"),
        ("verification_token", "TEXT"),
        ("token_created_at", "TIMESTAMP"),
    ]:
        if col not in existing_cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

    c.execute("""
        CREATE TABLE IF NOT EXISTS newsletters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            html_content TEXT NOT NULL,
            prompt_used TEXT,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            category TEXT NOT NULL,
            original_name TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Instructions table for Claude directives
    c.execute("""
        CREATE TABLE IF NOT EXISTS instructions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            updated_by TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Default admin
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if c.fetchone()[0] == 0:
        pw = get_secret("ADMIN_DEFAULT_PASSWORD")
        admin_email = get_secret("ADMIN_EMAIL", f"admin@{get_allowed_domains()[0]}")
        if not pw:
            st.error("ADMIN_DEFAULT_PASSWORD が未設定です。Secrets に設定してください。")
            raise RuntimeError("ADMIN_DEFAULT_PASSWORD is not configured")
        hashed = hash_password(pw)
        c.execute(
            "INSERT INTO users (username, email, hashed_password, role, is_verified) VALUES (?, ?, ?, ?, ?)",
            ("admin", admin_email, hashed, "admin", 1),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Instructions (Claude directives) helpers
# ---------------------------------------------------------------------------
def get_instruction(key: str, default: str = "") -> str:
    db = get_db()
    row = db.execute("SELECT value FROM instructions WHERE key = ?", (key,)).fetchone()
    db.close()
    return row["value"] if row else default


def set_instruction(key: str, value: str, username: str = ""):
    db = get_db()
    db.execute(
        """INSERT INTO instructions (key, value, updated_by, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
        (key, value, username, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_verification_email(to_email: str, token: str) -> bool:
    smtp_host = get_secret("SMTP_HOST")
    smtp_port = int(get_secret("SMTP_PORT", "587"))
    smtp_user = get_secret("SMTP_USER")
    smtp_password = get_secret("SMTP_PASSWORD")
    smtp_from = get_secret("SMTP_FROM", smtp_user)

    if not all([smtp_host, smtp_user, smtp_password]):
        st.error("SMTP設定が不完全です。管理者に連絡してください。")
        return False

    app_url = get_secret("APP_URL", "").rstrip("/")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "【Newsletter AI】メールアドレスの確認"
    msg["From"] = smtp_from
    msg["To"] = to_email

    if app_url:
        verify_link = f"{app_url}/?verify={token}"
        action_text = f"以下のボタンをクリックしてメールアドレスを確認してください。"
        action_html = f"""
            <p style="margin:30px 0;text-align:center;">
                <a href="{verify_link}"
                   style="background:#FB7185;color:#fff;padding:14px 32px;
                          text-decoration:none;border-radius:12px;font-size:16px;
                          font-weight:600;display:inline-block;">
                    メールアドレスを確認する
                </a>
            </p>
            <p style="color:#86868b;font-size:13px;">ボタンが動かない場合:<br>
               <a href="{verify_link}" style="color:#FB7185;word-break:break-all;">{verify_link}</a></p>
        """
    else:
        action_text = f"以下の認証コードをアプリの「認証コード入力」画面に入力してください。"
        action_html = f"""
            <p style="margin:24px 0;padding:20px;background:#f5f5f7;border-radius:12px;
                      font-family:monospace;font-size:20px;text-align:center;
                      letter-spacing:0.05em;font-weight:700;">{token}</p>
        """

    text_body = f"Newsletter AI\n\n{action_text}\n\n認証コード: {token}\n\n{VERIFICATION_TOKEN_EXPIRE_HOURS}時間有効です。"

    html_body = f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;
                       max-width:520px;margin:0 auto;padding:40px 20px;color:#1d1d1f;">
        <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em;margin-bottom:8px;">Newsletter AI</h1>
        <p style="color:#86868b;margin-bottom:32px;">メールアドレスの確認</p>
        <p>ご登録ありがとうございます。{action_text}</p>
        {action_html}
        <hr style="border:none;border-top:1px solid #d2d2d7;margin:32px 0;">
        <p style="color:#86868b;font-size:12px;">
            このリンクは{VERIFICATION_TOKEN_EXPIRE_HOURS}時間有効です。心当たりがない場合は無視してください。
        </p>
    </body></html>
    """

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"メール送信に失敗しました: {e}")
        return False


# ---------------------------------------------------------------------------
# Auth (admin-only login)
# ---------------------------------------------------------------------------
def authenticate_admin(password: str) -> dict | None:
    db = get_db()
    admin = db.execute("SELECT * FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    db.close()
    if admin and verify_password(password, admin["hashed_password"]):
        return {"username": admin["username"], "email": admin.get("email", ""), "role": "admin"}
    return None


def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        show_login_page()
        st.stop()
    last = st.session_state.get("last_activity", 0)
    if last and (time.time() - last) > SESSION_TIMEOUT_MINUTES * 60:
        st.session_state.clear()
        st.warning("セッションがタイムアウトしました。再度ログインしてください。")
        st.stop()
    st.session_state.last_activity = time.time()


def is_admin() -> bool:
    return True


# ---------------------------------------------------------------------------
# Login Page (admin password only)
# ---------------------------------------------------------------------------
def show_login_page():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
    st.markdown("<div class='auth-logo'>Newsletter AI</div>", unsafe_allow_html=True)
    st.markdown("<div class='auth-tagline'>AI-Powered Newsletter Creator</div>", unsafe_allow_html=True)

    # Lockout check
    locked_until = st.session_state.get("login_locked_until", 0)
    if locked_until and time.time() < locked_until:
        remaining = int(locked_until - time.time())
        st.error(f"ログイン試行上限に達しました。{remaining}秒後に再試行してください。")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if locked_until and time.time() >= locked_until:
        st.session_state.login_attempts = 0
        st.session_state.login_locked_until = 0

    with st.form("login_form"):
        password = st.text_input("パスワード", type="password", placeholder="管理者パスワードを入力")
        submitted = st.form_submit_button("ログイン", use_container_width=True, type="primary")

    if submitted:
        if not password:
            st.error("パスワードを入力してください")
        else:
            result = authenticate_admin(password)
            if result:
                st.session_state.login_attempts = 0
                st.session_state.login_locked_until = 0
                st.session_state.user = result
                st.session_state.last_activity = time.time()
                st.rerun()
            else:
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state.login_attempts = attempts
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    st.session_state.login_locked_until = time.time() + LOGIN_LOCKOUT_SECONDS
                    st.error(f"{LOGIN_LOCKOUT_SECONDS // 60}分間ロックされます。")
                else:
                    remaining = MAX_LOGIN_ATTEMPTS - attempts
                    st.error(f"パスワードが正しくありません（残り{remaining}回）")

    st.markdown("</div>", unsafe_allow_html=True)



# ---------------------------------------------------------------------------
# Page: Generate
# ---------------------------------------------------------------------------
def page_generate():
    st.markdown("<div class='page-title'>メルマガ生成</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-subtitle'>AIがプロ品質のメルマガを作成します</div>", unsafe_allow_html=True)

    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY が未設定です。管理者に連絡してください。")
        return

    # Notion integration - direct page references
    notion_token = get_secret("NOTION_API_KEY")
    NOTION_PAGES = {
        "NOTION_PAGE_SHOHIN": "商品情報",
        "NOTION_PAGE_GAIBU": "外部情報",
        "NOTION_PAGE_MIRYOKU": "魅力情報",
        "NOTION_PAGE_QA": "Q&A",
    }
    notion_pages_config = {}
    for key, label in NOTION_PAGES.items():
        page_id = get_secret(key)
        if page_id:
            notion_pages_config[key] = {"id": page_id, "label": label}
    use_notion = bool(notion_token and notion_pages_config)

    # Reference source selection
    source_options = ["なし"]
    if use_notion:
        source_options.append("Notion")
    source_options.append("アップロードファイル")

    ref_source = st.radio("参考データソース", source_options, horizontal=True)

    selected_files = []
    selected_notion_keys = []

    if ref_source == "Notion" and use_notion:
        st.caption("参照する Notion ページを選択してください")

        # Show each page with connection status and checkbox
        for page_key, page_meta in notion_pages_config.items():
            page_info = _fetch_notion_page_info(notion_token, page_meta["id"])
            if page_info:
                col1, col2 = st.columns([5, 1])
                with col1:
                    checked = st.checkbox(
                        f"**{page_meta['label']}** — {page_info['title']}",
                        key=f"notion_{page_key}",
                    )
                    if checked:
                        selected_notion_keys.append(page_key)
                with col2:
                    if page_info.get("url"):
                        st.markdown(f"<a href='{page_info['url']}' target='_blank' style='font-size:0.8rem;color:var(--accent);'>開く</a>", unsafe_allow_html=True)
            else:
                st.markdown(f"""<div style='padding:0.5rem 0;'>
                    <span class='badge-pending'>未接続</span>&nbsp;
                    {page_meta['label']}（インテグレーションの共有設定を確認）
                </div>""", unsafe_allow_html=True)

    elif ref_source == "アップロードファイル":
        db = get_db()
        files = db.execute("SELECT * FROM uploaded_files ORDER BY category, original_name").fetchall()
        db.close()
        if files:
            for cat_key, cat_label in ALLOWED_CATEGORIES.items():
                cat_files = [f for f in files if f["category"] == cat_key]
                if cat_files:
                    st.markdown(f"**{cat_label}**")
                    for f in cat_files:
                        if st.checkbox(f["original_name"], key=f"file_{f['id']}"):
                            selected_files.append(f"{f['category']}/{f['filename']}")

    st.markdown("---")

    # Decoration templates (multiple selection)
    db_conn = get_db()
    deco_files = db_conn.execute(
        "SELECT * FROM uploaded_files WHERE category = 'decoration' ORDER BY original_name"
    ).fetchall()
    db_conn.close()

    selected_templates = []
    if deco_files:
        template_map = {f"{f['category']}/{f['filename']}": f["original_name"] for f in deco_files}
        selected_templates = st.multiselect(
            "装飾テンプレート（複数選択可）",
            options=list(template_map.keys()),
            format_func=lambda x: template_map[x],
            help="複数選択するとデザインパターンをより正確に再現します",
        )

        if selected_templates:
            with st.expander(f"テンプレート プレビュー（{len(selected_templates)}件）"):
                for tpl_key in selected_templates:
                    tpl_path = os.path.join(UPLOAD_DIR, tpl_key)
                    if os.path.exists(tpl_path):
                        st.caption(template_map[tpl_key])
                        tpl_html = read_file_content(tpl_path)
                        st.components.v1.html(tpl_html, height=300, scrolling=True)
                        st.markdown("---")
    else:
        st.caption("装飾テンプレートなし（ファイル管理 → 装飾テンプレートからHTMLをアップロード）")

    with st.form("generate_form"):
        prompt = st.text_area("作成指示", placeholder="例: 春の新商品キャンペーンのお知らせメルマガを作成してください", height=100)
        length = st.selectbox("ボリューム", ["short", "medium", "long"], index=1,
                              format_func=lambda x: {"short": "短め（800〜1200字）", "medium": "標準（1500〜2500字）", "long": "長め（3000〜5000字）"}[x])
        submitted = st.form_submit_button("生成する", use_container_width=True, type="primary")

    if submitted:
        if not prompt.strip():
            st.warning("作成指示を入力してください")
            return

        with st.spinner("メルマガを生成中..."):
            try:
                os.environ["ANTHROPIC_API_KEY"] = api_key
                os.environ["CLAUDE_MODEL"] = get_secret("CLAUDE_MODEL", "claude-sonnet-4-6")

                # Build reference data
                extra_context = ""
                if ref_source == "Notion" and use_notion and selected_notion_keys:
                    for page_key in selected_notion_keys:
                        page_meta = notion_pages_config[page_key]
                        content = _fetch_notion_page_content(notion_token, page_meta["id"])
                        extra_context += f"\n### {page_meta['label']}\n{content}\n"

                # Extract style from decoration templates
                template_style_summary = None
                if selected_templates:
                    from ai_service import extract_multi_template_summary
                    tpl_data = []
                    for tpl_key in selected_templates:
                        tpl_path = os.path.join(UPLOAD_DIR, tpl_key)
                        if os.path.exists(tpl_path):
                            tpl_content = read_file_content(tpl_path)
                            tpl_name = template_map.get(tpl_key, tpl_key)
                            tpl_data.append((tpl_name, tpl_content))
                    if tpl_data:
                        template_style_summary = extract_multi_template_summary(tpl_data)

                # Load instructions
                footer_text = get_instruction("footer")
                custom_instructions = get_instruction("custom_instructions")

                import asyncio
                result = asyncio.run(generate_newsletter(
                    prompt=prompt, length=length,
                    template_style_summary=template_style_summary,
                    selected_files=selected_files if selected_files else None,
                    extra_context=extra_context if extra_context else None,
                    footer_html=footer_text if footer_text else None,
                    custom_instructions=custom_instructions if custom_instructions else None,
                ))
                st.session_state.generated_html = result["html"]
                st.session_state.generated_prompt = prompt
                st.session_state.tokens_used = result["tokens_used"]
            except Exception as e:
                st.error(f"生成エラー: {e}")
                return

    # Result display (FIX #4: Preview + HTML code)
    if "generated_html" in st.session_state:
        st.markdown(f"""<div class='stat-row'>
            <div class='stat-box'><div class='stat-value'>{st.session_state.tokens_used:,}</div>
            <div class='stat-label'>Tokens Used</div></div>
        </div>""", unsafe_allow_html=True)

        tab_preview, tab_code = st.tabs(["プレビュー", "HTML コード"])
        with tab_preview:
            st.components.v1.html(st.session_state.generated_html, height=600, scrolling=True)
        with tab_code:
            st.code(st.session_state.generated_html, language="html")

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("HTML ダウンロード", st.session_state.generated_html,
                               file_name="newsletter.html", mime="text/html", use_container_width=True)
        with col2:
            with st.form("save_form"):
                title = st.text_input("タイトル", placeholder="保存名を入力", label_visibility="collapsed")
                save_btn = st.form_submit_button("保存する", use_container_width=True)
            if save_btn and title.strip():
                db = get_db()
                db.execute(
                    "INSERT INTO newsletters (title, html_content, prompt_used, created_by) VALUES (?, ?, ?, ?)",
                    (title, st.session_state.generated_html, st.session_state.generated_prompt,
                     st.session_state.user["username"]),
                )
                db.commit()
                db.close()
                st.success("保存しました")


# ---------------------------------------------------------------------------
# Page: History (FIX #4: add HTML code tab to history)
# ---------------------------------------------------------------------------
def page_history():
    st.markdown("<div class='page-title'>生成履歴</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-subtitle'>過去に生成したメルマガ一覧</div>", unsafe_allow_html=True)

    db = get_db()
    newsletters = db.execute("SELECT * FROM newsletters ORDER BY created_at DESC LIMIT 50").fetchall()
    db.close()

    if not newsletters:
        st.info("まだ履歴がありません")
        return

    for nl in newsletters:
        with st.expander(f"{nl['title']}  —  {nl['created_at'][:16]}  ·  {nl['created_by']}"):
            if nl["prompt_used"]:
                st.caption(f"プロンプト: {nl['prompt_used']}")

            tab_p, tab_c = st.tabs(["プレビュー", "HTML コード"])
            with tab_p:
                st.components.v1.html(nl["html_content"], height=400, scrolling=True)
            with tab_c:
                st.code(nl["html_content"], language="html")

            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.download_button("HTML ダウンロード", nl["html_content"],
                                   file_name=f"{nl['title']}.html", mime="text/html",
                                   key=f"dl_{nl['id']}", use_container_width=True)
            with col3:
                if is_admin():
                    if st.button("削除", key=f"del_{nl['id']}"):
                        db = get_db()
                        db.execute("DELETE FROM newsletters WHERE id = ?", (nl["id"],))
                        db.commit()
                        db.close()
                        st.rerun()


# ---------------------------------------------------------------------------
# Page: Files
# ---------------------------------------------------------------------------
def page_files():
    st.markdown("<div class='page-title'>ファイル管理</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-subtitle'>メルマガ生成に使用する参考データ</div>", unsafe_allow_html=True)

    if is_admin():
        with st.form("upload_form", clear_on_submit=True):
            col1, col2 = st.columns([1, 2])
            with col1:
                category = st.selectbox("カテゴリ", list(ALLOWED_CATEGORIES.keys()),
                                        format_func=lambda x: ALLOWED_CATEGORIES[x])
            with col2:
                uploaded = st.file_uploader("ファイル", type=["txt", "csv", "pdf", "text", "md", "html", "htm"],
                                            label_visibility="collapsed")
            upload_btn = st.form_submit_button("アップロード", use_container_width=True)

        if upload_btn and uploaded:
            content = uploaded.read()
            if len(content) > MAX_UPLOAD_SIZE:
                st.error("ファイルサイズが大きすぎます（最大10MB）")
            else:
                safe_name = f"{uuid.uuid4().hex[:8]}_{uploaded.name}"
                cat_dir = os.path.join(UPLOAD_DIR, category)
                os.makedirs(cat_dir, exist_ok=True)
                with open(os.path.join(cat_dir, safe_name), "wb") as f:
                    f.write(content)
                db = get_db()
                db.execute(
                    "INSERT INTO uploaded_files (filename, category, original_name, uploaded_by) VALUES (?, ?, ?, ?)",
                    (safe_name, category, uploaded.name, st.session_state.user["username"]),
                )
                db.commit()
                db.close()
                st.success(f"「{uploaded.name}」をアップロードしました")

    db = get_db()
    files = db.execute("SELECT * FROM uploaded_files ORDER BY uploaded_at DESC").fetchall()
    db.close()

    if not files:
        st.info("ファイルがありません")
        return

    for cat_key, cat_label in ALLOWED_CATEGORIES.items():
        cat_files = [f for f in files if f["category"] == cat_key]
        if cat_files:
            st.markdown(f"#### {cat_label}")
            for f in cat_files:
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.caption(f"{f['original_name']}  ·  {f['uploaded_at'][:16]}  ·  {f['uploaded_by']}")
                with col2:
                    if is_admin():
                        if st.button("削除", key=f"fdel_{f['id']}"):
                            filepath = os.path.join(UPLOAD_DIR, f["category"], f["filename"])
                            if os.path.exists(filepath):
                                os.remove(filepath)
                            db = get_db()
                            db.execute("DELETE FROM uploaded_files WHERE id = ?", (f["id"],))
                            db.commit()
                            db.close()
                            st.rerun()


# ---------------------------------------------------------------------------
# Page: Instructions (FIX #5)
# ---------------------------------------------------------------------------
def page_instructions():
    st.markdown("<div class='page-title'>指示書設定</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-subtitle'>メルマガ生成時に Claude に自動適用される指示</div>", unsafe_allow_html=True)

    if not is_admin():
        st.warning("管理者権限が必要です")
        return

    st.markdown("#### カスタム指示")
    st.caption("トーン、使用する言葉、避ける表現、ブランドガイドライン等を記述してください。全ての生成に自動適用されます。")
    current_instructions = get_instruction("custom_instructions")
    new_instructions = st.text_area(
        "指示内容", value=current_instructions, height=200, label_visibility="collapsed",
        placeholder="例:\n- 「お客様」ではなく「皆さま」を使用\n- 絵文字は控えめに\n- 必ず会社名「Androots」を冒頭に入れる\n- CTAボタンの文言は「詳しくはこちら」で統一",
    )

    st.markdown("---")

    st.markdown("#### フッター HTML")
    st.caption("全てのメルマガの末尾に自動挿入される固定フッターです。HTML で記述できます。")
    current_footer = get_instruction("footer")
    new_footer = st.text_area(
        "フッター", value=current_footer, height=200, label_visibility="collapsed",
        placeholder='例:\n<div style="text-align:center;padding:20px;color:#86868b;font-size:12px;">\n  <p>株式会社Androots</p>\n  <p>〒000-0000 東京都...</p>\n  <p><a href="#">配信停止</a></p>\n</div>',
    )

    if new_footer != current_footer:
        with st.expander("フッター プレビュー"):
            if new_footer.strip():
                st.components.v1.html(new_footer, height=150, scrolling=True)
            else:
                st.caption("（空）")

    if st.button("保存する", type="primary", use_container_width=True):
        username = st.session_state.user["username"]
        set_instruction("custom_instructions", new_instructions, username)
        set_instruction("footer", new_footer, username)
        st.success("指示書を保存しました")


# ---------------------------------------------------------------------------
# Page: Users
# ---------------------------------------------------------------------------
def page_users():
    if not is_admin():
        st.warning("管理者権限が必要です")
        return

    st.markdown("<div class='page-title'>ユーザー管理</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-subtitle'>チームメンバーの招待と管理</div>", unsafe_allow_html=True)

    with st.form("add_user_form", clear_on_submit=True):
        st.markdown("#### 新規ユーザー招待")
        col1, col2 = st.columns(2)
        with col1:
            new_username = st.text_input("表示名")
            new_role = st.selectbox("ロール", ["user", "admin"])
        with col2:
            new_email = st.text_input("メールアドレス", placeholder=f"name@{get_allowed_domains()[0]}")
            new_password = st.text_input("初期パスワード", type="password", help="10文字以上・英数字必須")
        add_btn = st.form_submit_button("追加して確認メールを送信", use_container_width=True, type="primary")

    if add_btn:
        if not all([new_username, new_email, new_password]):
            st.error("全項目を入力してください")
        elif not validate_email_domain(new_email):
            st.error(f"{_domains_display()} のみ登録可能です")
        elif len(new_password) < 10:
            st.error("パスワードは10文字以上")
        elif not any(c.isdigit() for c in new_password) or not any(c.isalpha() for c in new_password):
            st.error("英字と数字を両方含めてください")
        else:
            new_email = new_email.strip().lower()
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ? OR username = ?", (new_email, new_username)).fetchone()
            if existing:
                st.error("このメールアドレスまたは表示名は使用済みです")
            else:
                token = uuid.uuid4().hex
                hashed = hash_password(new_password)
                db.execute(
                    """INSERT INTO users (username, email, hashed_password, role, is_verified, verification_token, token_created_at)
                       VALUES (?, ?, ?, ?, 0, ?, ?)""",
                    (new_username, new_email, hashed, new_role, token, datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
                db.close()
                if send_verification_email(new_email, token):
                    st.success(f"確認メールを {new_email} に送信しました")
                else:
                    st.warning("ユーザー作成済みですが、メール送信に失敗しました")

    st.markdown("---")
    st.markdown("#### メンバー一覧")

    db = get_db()
    users = db.execute("SELECT id, username, email, role, is_verified, created_at FROM users ORDER BY id").fetchall()
    db.close()

    for u in users:
        col1, col2, col3, col4 = st.columns([3, 3, 1, 2])
        with col1:
            st.markdown(f"**{u['username']}**")
        with col2:
            st.caption(u["email"] or "-")
        with col3:
            if u["is_verified"]:
                st.markdown("<span class='badge-ok'>認証済</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='badge-pending'>未認証</span>", unsafe_allow_html=True)
        with col4:
            if u["username"] != "admin":
                bc1, bc2 = st.columns(2)
                with bc1:
                    if not u["is_verified"]:
                        if st.button("再送", key=f"resend_{u['id']}"):
                            token = uuid.uuid4().hex
                            db = get_db()
                            db.execute("UPDATE users SET verification_token = ?, token_created_at = ? WHERE id = ?",
                                       (token, datetime.now(timezone.utc).isoformat(), u["id"]))
                            db.commit()
                            db.close()
                            send_verification_email(u["email"], token)
                            st.rerun()
                with bc2:
                    if st.button("削除", key=f"udel_{u['id']}"):
                        db = get_db()
                        db.execute("DELETE FROM users WHERE id = ?", (u["id"],))
                        db.commit()
                        db.close()
                        st.rerun()


# ---------------------------------------------------------------------------
# Notion integration (FIX #3)
# ---------------------------------------------------------------------------
def _fetch_notion_page_info(token: str, page_id: str) -> dict | None:
    """Notion ページのタイトル・URL を取得"""
    try:
        import requests
        resp = requests.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        title = ""
        for prop in data.get("properties", {}).values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                break
        return {
            "title": title or "Untitled",
            "url": data.get("url", ""),
            "id": page_id,
        }
    except Exception:
        return None


def _fetch_notion_page_content(token: str, page_id: str) -> str:
    """Notion ページのブロック内容をテキストで取得"""
    try:
        import requests
        resp = requests.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
            timeout=10,
        )
        resp.raise_for_status()
        texts = []
        for block in resp.json().get("results", []):
            block_type = block.get("type", "")
            block_data = block.get(block_type, {})
            if "rich_text" in block_data:
                line = "".join(t.get("plain_text", "") for t in block_data["rich_text"])
                if line.strip():
                    texts.append(line)
        return "\n".join(texts)
    except Exception as e:
        return f"[Notion読み取りエラー: {e}]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Newsletter AI", page_icon="📧", layout="wide")

    init_db()
    require_login()

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("#### Newsletter AI")
        st.markdown(f"<span style='font-size:0.8rem;opacity:0.7;'>{st.session_state.user['username']}</span>", unsafe_allow_html=True)

        st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)

        pages = ["メルマガ生成", "生成履歴", "ファイル管理"]
        if is_admin():
            pages += ["指示書設定"]
        page = st.radio("メニュー", pages, label_visibility="collapsed")

        st.markdown("<div style='flex:1;'></div>", unsafe_allow_html=True)
        st.divider()
        if st.button("ログアウト", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    if page == "メルマガ生成":
        page_generate()
    elif page == "生成履歴":
        page_history()
    elif page == "ファイル管理":
        page_files()
    elif page == "指示書設定":
        page_instructions()


if __name__ == "__main__":
    main()
else:
    main()
