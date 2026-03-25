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
# Apple-inspired CSS
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    --bg: #f5f5f7;
    --card: #ffffff;
    --text: #1d1d1f;
    --text-secondary: #86868b;
    --accent: #0071e3;
    --accent-hover: #0077ED;
    --border: #d2d2d7;
    --success: #34c759;
    --danger: #ff3b30;
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: var(--text);
}

.main .block-container {
    max-width: 960px;
    padding: 2rem 1.5rem;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--card);
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] .stRadio > label {
    font-size: 0.85rem;
    font-weight: 500;
}

/* Cards */
.app-card {
    background: var(--card);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    border: 1px solid var(--border);
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

/* Headers */
.page-title {
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
    color: var(--text);
}
.page-subtitle {
    font-size: 1rem;
    color: var(--text-secondary);
    font-weight: 400;
    margin-bottom: 2rem;
}

/* Auth page */
.auth-container {
    max-width: 420px;
    margin: 4rem auto;
}
.auth-logo {
    font-size: 2.5rem;
    font-weight: 700;
    text-align: center;
    letter-spacing: -0.03em;
    margin-bottom: 0.25rem;
}
.auth-tagline {
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.95rem;
    margin-bottom: 2rem;
}

/* Buttons */
.stButton > button {
    border-radius: 12px !important;
    font-weight: 500 !important;
    padding: 0.5rem 1.5rem !important;
    transition: all 0.2s ease !important;
    border: 1px solid var(--border) !important;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.1) !important;
}
.stButton > button[kind="primary"] {
    background: var(--accent) !important;
    color: white !important;
    border: none !important;
}

/* Form */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
    border-radius: 10px !important;
    border: 1px solid var(--border) !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(0,113,227,0.15) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: var(--bg);
    border-radius: 10px;
    padding: 3px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    font-weight: 500;
    font-size: 0.85rem;
    padding: 0.5rem 1rem;
}
.stTabs [aria-selected="true"] {
    background: var(--card) !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

/* Expander */
.streamlit-expanderHeader {
    border-radius: 12px !important;
    font-weight: 500 !important;
}

/* Metric */
.stat-row {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
}
.stat-box {
    flex: 1;
    background: var(--bg);
    border-radius: 12px;
    padding: 1rem;
    text-align: center;
}
.stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text);
}
.stat-label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Notification badges */
.badge-ok {
    display: inline-block;
    background: #e8f8ee;
    color: #1a7f37;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
}
.badge-pending {
    display: inline-block;
    background: #fff3e0;
    color: #e65100;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
}

/* Hide Streamlit branding */
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
                   style="background:#0071e3;color:#fff;padding:14px 32px;
                          text-decoration:none;border-radius:12px;font-size:16px;
                          font-weight:600;display:inline-block;">
                    メールアドレスを確認する
                </a>
            </p>
            <p style="color:#86868b;font-size:13px;">ボタンが動かない場合:<br>
               <a href="{verify_link}" style="color:#0071e3;word-break:break-all;">{verify_link}</a></p>
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
# Auth
# ---------------------------------------------------------------------------
def authenticate(email: str, password: str) -> dict | None:
    email = email.strip().lower()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    db.close()
    if user and verify_password(password, user["hashed_password"]):
        if not user["is_verified"]:
            return {"error": "unverified"}
        return {"username": user["username"], "email": user["email"], "role": user["role"]}
    return None


def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        show_auth_page()
        st.stop()
    last = st.session_state.get("last_activity", 0)
    if last and (time.time() - last) > SESSION_TIMEOUT_MINUTES * 60:
        st.session_state.clear()
        st.warning("セッションがタイムアウトしました。再度ログインしてください。")
        st.stop()
    st.session_state.last_activity = time.time()


def is_admin() -> bool:
    return st.session_state.get("user", {}).get("role") == "admin"


# ---------------------------------------------------------------------------
# Verification (FIX #1: handle before init_db / login check)
# ---------------------------------------------------------------------------
def handle_email_verification() -> bool:
    """URL の ?verify= パラメータを処理。認証成功なら True を返す"""
    params = st.query_params
    token = params.get("verify")
    if not token:
        return False

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE verification_token = ?", (token,)).fetchone()

    if not user:
        db.close()
        st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
        st.error("無効な認証リンクです。リンクの有効期限が切れているか、既に認証済みです。")
        if st.button("ログイン画面へ"):
            st.query_params.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return True

    token_time = datetime.fromisoformat(user["token_created_at"])
    now = datetime.now(timezone.utc)
    if token_time.tzinfo is None:
        token_time = token_time.replace(tzinfo=timezone.utc)

    if now - token_time > timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS):
        db.close()
        st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
        st.error("認証リンクの有効期限が切れています。管理者に再送を依頼してください。")
        if st.button("ログイン画面へ"):
            st.query_params.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return True

    db.execute(
        "UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?",
        (user["id"],),
    )
    db.commit()
    db.close()

    st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
    st.markdown("<div class='auth-logo'>Newsletter AI</div>", unsafe_allow_html=True)
    st.success(f"{user['email']} の認証が完了しました。")
    st.info("ログイン画面からログインしてください。")
    if st.button("ログイン画面へ", type="primary", use_container_width=True):
        st.query_params.clear()
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    return True


# ---------------------------------------------------------------------------
# Auth Page
# ---------------------------------------------------------------------------
def _check_login_lockout() -> bool:
    locked_until = st.session_state.get("login_locked_until", 0)
    if locked_until and time.time() < locked_until:
        remaining = int(locked_until - time.time())
        st.error(f"ログイン試行上限に達しました。{remaining}秒後に再試行してください。")
        return True
    if locked_until and time.time() >= locked_until:
        st.session_state.login_attempts = 0
        st.session_state.login_locked_until = 0
    return False


def _record_failed_login():
    attempts = st.session_state.get("login_attempts", 0) + 1
    st.session_state.login_attempts = attempts
    if attempts >= MAX_LOGIN_ATTEMPTS:
        st.session_state.login_locked_until = time.time() + LOGIN_LOCKOUT_SECONDS


def show_auth_page():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
    st.markdown("<div class='auth-logo'>Newsletter AI</div>", unsafe_allow_html=True)
    st.markdown("<div class='auth-tagline'>AI-Powered Newsletter Creator</div>", unsafe_allow_html=True)

    tab_login, tab_register, tab_verify = st.tabs(["ログイン", "新規登録", "認証コード"])

    with tab_login:
        if _check_login_lockout():
            return
        with st.form("login_form"):
            email = st.text_input("メールアドレス", placeholder=f"name@{get_allowed_domains()[0]}")
            password = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("ログイン", use_container_width=True, type="primary")
        if submitted:
            if not email or not password:
                st.error("メールアドレスとパスワードを入力してください")
            elif not validate_email_domain(email):
                st.error(f"{_domains_display()} のみ使用できます")
            else:
                result = authenticate(email, password)
                if result and "error" not in result:
                    st.session_state.login_attempts = 0
                    st.session_state.login_locked_until = 0
                    st.session_state.user = result
                    st.session_state.last_activity = time.time()
                    st.rerun()
                elif result and result.get("error") == "unverified":
                    st.warning("メール未認証です。確認メールのリンクをクリックするか「認証コード」タブへ。")
                else:
                    _record_failed_login()
                    remaining = MAX_LOGIN_ATTEMPTS - st.session_state.get("login_attempts", 0)
                    if remaining > 0:
                        st.error(f"認証失敗（残り{remaining}回）")
                    else:
                        st.error(f"{LOGIN_LOCKOUT_SECONDS // 60}分間ロックされます。")

    with tab_register:
        st.caption(f"{_domains_display()} のメールアドレスが必要です")
        with st.form("register_form"):
            reg_username = st.text_input("表示名", placeholder="山田太郎")
            reg_email = st.text_input("メールアドレス", placeholder=f"name@{get_allowed_domains()[0]}")
            reg_password = st.text_input("パスワード", type="password", help="10文字以上・英数字必須")
            reg_password2 = st.text_input("パスワード（確認）", type="password")
            reg_submitted = st.form_submit_button("登録する", use_container_width=True, type="primary")
        if reg_submitted:
            if not all([reg_username, reg_email, reg_password, reg_password2]):
                st.error("全項目を入力してください")
            elif not validate_email_domain(reg_email):
                st.error(f"{_domains_display()} のみ登録可能です")
            elif len(reg_password) < 10:
                st.error("パスワードは10文字以上")
            elif not any(c.isdigit() for c in reg_password) or not any(c.isalpha() for c in reg_password):
                st.error("英字と数字を両方含めてください")
            elif reg_password != reg_password2:
                st.error("パスワードが一致しません")
            else:
                reg_email = reg_email.strip().lower()
                db = get_db()
                existing = db.execute(
                    "SELECT id FROM users WHERE email = ? OR username = ?",
                    (reg_email, reg_username),
                ).fetchone()
                if existing:
                    db.close()
                    st.error("このメールアドレスまたは表示名は使用済みです")
                else:
                    token = uuid.uuid4().hex
                    hashed = hash_password(reg_password)
                    db.execute(
                        """INSERT INTO users (username, email, hashed_password, role, is_verified, verification_token, token_created_at)
                           VALUES (?, ?, ?, 'user', 0, ?, ?)""",
                        (reg_username, reg_email, hashed, token, datetime.now(timezone.utc).isoformat()),
                    )
                    db.commit()
                    db.close()
                    if send_verification_email(reg_email, token):
                        st.success(f"確認メールを {reg_email} に送信しました。")
                    else:
                        st.warning("ユーザー作成済みですが、メール送信に失敗しました。")

    with tab_verify:
        st.caption("確認メールの認証コードを入力")
        with st.form("verify_form"):
            verify_token = st.text_input("認証コード")
            verify_submitted = st.form_submit_button("認証する", use_container_width=True, type="primary")
        if verify_submitted and verify_token:
            verify_token = verify_token.strip()
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE verification_token = ?", (verify_token,)).fetchone()
            if not user:
                db.close()
                st.error("無効な認証コードです")
            else:
                token_time = datetime.fromisoformat(user["token_created_at"])
                if token_time.tzinfo is None:
                    token_time = token_time.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - token_time > timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS):
                    db.close()
                    st.error("認証コードの有効期限が切れています。")
                else:
                    db.execute("UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?", (user["id"],))
                    db.commit()
                    db.close()
                    st.success(f"{user['email']} の認証完了！「ログイン」タブへ。")

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

    # FIX #1: Handle verification URL BEFORE anything else
    if handle_email_verification():
        st.stop()

    init_db()
    require_login()

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### Newsletter AI")
        st.caption(f"{st.session_state.user['username']}  ·  {st.session_state.user['email']}")

        pages = ["メルマガ生成", "生成履歴", "ファイル管理"]
        if is_admin():
            pages += ["指示書設定", "ユーザー管理"]
        page = st.radio("メニュー", pages, label_visibility="collapsed")

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
    elif page == "ユーザー管理":
        page_users()


if __name__ == "__main__":
    main()
else:
    main()
