"""
Newsletter AI - Streamlit App
社内向けメルマガ生成ツール（セキュアなチーム共有版）
メール認証: 許可ドメインのみ（デフォルト: @androots.co.jp）
"""

import os
import uuid
import sqlite3
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

import bcrypt
import streamlit as st

from ai_service import generate_newsletter, read_file_content

# ---------------------------------------------------------------------------
# セキュリティ定数
# ---------------------------------------------------------------------------
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300
SESSION_TIMEOUT_MINUTES = 60
VERIFICATION_TOKEN_EXPIRE_HOURS = 24

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_CATEGORIES = {"products": "商品情報", "instructions": "指示書", "templates": "テンプレート"}
ALLOWED_EXTENSIONS = {".txt", ".csv", ".pdf", ".text", ".md"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def get_secret(key: str, default: str = "") -> str:
    """st.secrets -> 環境変数 -> デフォルトの優先順位で取得"""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.environ.get(key, default)


def get_allowed_domains() -> list[str]:
    """許可メールドメインのリストを取得。カンマ区切りで複数指定可能"""
    raw = get_secret("ALLOWED_EMAIL_DOMAINS", "androots.co.jp")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _domains_display() -> str:
    """UIに表示する許可ドメイン文字列"""
    domains = get_allowed_domains()
    return " / ".join(f"@{d}" for d in domains)


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

    # Migrate: add columns if they don't exist (for existing DBs)
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
    if "is_verified" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
    if "verification_token" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN verification_token TEXT")
    if "token_created_at" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN token_created_at TIMESTAMP")

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

    # Default admin (pre-verified)
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if c.fetchone()[0] == 0:
        pw = get_secret("ADMIN_DEFAULT_PASSWORD")
        admin_email = get_secret("ADMIN_EMAIL", f"admin@{get_allowed_domains()[0]}")
        if not pw:
            st.error("ADMIN_DEFAULT_PASSWORD が未設定です。Secrets または環境変数に設定してください。")
            raise RuntimeError("ADMIN_DEFAULT_PASSWORD is not configured")
        hashed = hash_password(pw)
        c.execute(
            "INSERT INTO users (username, email, hashed_password, role, is_verified) VALUES (?, ?, ?, ?, ?)",
            ("admin", admin_email, hashed, "admin", 1),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def validate_email_domain(email: str) -> bool:
    """許可ドメインのメールアドレスのみ受け付ける"""
    email = email.strip().lower()
    return any(email.endswith(f"@{d}") for d in get_allowed_domains())


def send_verification_email(to_email: str, token: str) -> bool:
    """確認メールを送信"""
    smtp_host = get_secret("SMTP_HOST")
    smtp_port = int(get_secret("SMTP_PORT", "587"))
    smtp_user = get_secret("SMTP_USER")
    smtp_password = get_secret("SMTP_PASSWORD")
    smtp_from = get_secret("SMTP_FROM", smtp_user)

    if not all([smtp_host, smtp_user, smtp_password]):
        st.error("SMTP設定が不完全です。管理者に連絡してください。")
        return False

    app_url = get_secret("APP_URL", "")
    if app_url:
        verify_link = f"{app_url}?verify={token}"
    else:
        verify_link = f"（アプリを開いて認証コード入力画面で以下のコードを入力してください）\n認証コード: {token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "【Newsletter AI】メールアドレスの確認"
    msg["From"] = smtp_from
    msg["To"] = to_email

    text_body = f"""Newsletter AI へのご登録ありがとうございます。

以下のリンクをクリックしてメールアドレスを確認してください。
{verify_link}

このリンクは {VERIFICATION_TOKEN_EXPIRE_HOURS} 時間有効です。
心当たりがない場合は、このメールを無視してください。
"""

    html_body = f"""
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #4F46E5;">Newsletter AI - メールアドレスの確認</h2>
    <p>Newsletter AI へのご登録ありがとうございます。</p>
    <p>以下のボタンをクリックしてメールアドレスを確認してください。</p>
    {"<p style='margin: 30px 0;'><a href='" + app_url + "?verify=" + token + "' style='background-color: #4F46E5; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-size: 16px;'>メールアドレスを確認する</a></p>" if app_url else "<p style='margin: 20px 0; padding: 15px; background: #f3f4f6; border-radius: 6px; font-family: monospace; font-size: 18px; text-align: center;'>認証コード: <strong>" + token + "</strong></p>"}
    <p style="color: #6b7280; font-size: 14px;">このリンクは {VERIFICATION_TOKEN_EXPIRE_HOURS} 時間有効です。</p>
    <p style="color: #6b7280; font-size: 14px;">心当たりがない場合は、このメールを無視してください。</p>
</body>
</html>
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
# Auth helpers
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
# Auth Pages
# ---------------------------------------------------------------------------
def _check_login_lockout() -> bool:
    locked_until = st.session_state.get("login_locked_until", 0)
    if locked_until and time.time() < locked_until:
        remaining = int(locked_until - time.time())
        st.error(f"ログイン試行回数が上限に達しました。{remaining}秒後に再試行してください。")
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


def verify_token_from_url():
    """URLパラメータからの認証トークン処理"""
    params = st.query_params
    token = params.get("verify")
    if not token:
        return

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE verification_token = ?", (token,)
    ).fetchone()

    if not user:
        db.close()
        st.error("無効な認証リンクです。")
        return

    token_time = datetime.fromisoformat(user["token_created_at"])
    if datetime.now(timezone.utc) - token_time > timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS):
        db.close()
        st.error("認証リンクの有効期限が切れています。管理者に再送を依頼してください。")
        return

    db.execute(
        "UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?",
        (user["id"],),
    )
    db.commit()
    db.close()
    st.success(f"メールアドレス ({user['email']}) の認証が完了しました！ログインしてください。")
    st.query_params.clear()


def show_auth_page():
    """ログイン / 新規登録 / 認証コード入力の統合ページ"""

    # URLパラメータからの自動認証
    verify_token_from_url()

    tab_login, tab_register, tab_verify = st.tabs(["ログイン", "新規登録", "認証コード入力"])

    # --- ログイン ---
    with tab_login:
        st.markdown("## Newsletter AI にログイン")
        if _check_login_lockout():
            return

        with st.form("login_form"):
            email = st.text_input("メールアドレス", placeholder="yourname@androots.co.jp")
            password = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("ログイン", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("メールアドレスとパスワードを入力してください")
                return
            if not validate_email_domain(email):
                st.error(f"{_domains_display()} のメールアドレスのみ使用できます")
                return

            result = authenticate(email, password)
            if result and "error" not in result:
                st.session_state.login_attempts = 0
                st.session_state.login_locked_until = 0
                st.session_state.user = result
                st.session_state.last_activity = time.time()
                st.rerun()
            elif result and result.get("error") == "unverified":
                st.warning("メールアドレスが未認証です。確認メールのリンクをクリックするか、「認証コード入力」タブで認証してください。")
            else:
                _record_failed_login()
                remaining = MAX_LOGIN_ATTEMPTS - st.session_state.get("login_attempts", 0)
                if remaining > 0:
                    st.error(f"メールアドレスまたはパスワードが正しくありません（残り{remaining}回）")
                else:
                    st.error(f"ログイン試行回数の上限に達しました。{LOGIN_LOCKOUT_SECONDS // 60}分間ロックされます。")

    # --- 新規登録 ---
    with tab_register:
        st.markdown("## 新規ユーザー登録")
        st.info(f"{_domains_display()} のメールアドレスが必要です")

        with st.form("register_form"):
            reg_username = st.text_input("表示名", placeholder="例: 山田太郎")
            reg_email = st.text_input("メールアドレス", placeholder=f"yourname@{get_allowed_domains()[0]}")
            reg_password = st.text_input("パスワード（10文字以上・英数字必須）", type="password")
            reg_password2 = st.text_input("パスワード（確認）", type="password")
            reg_submitted = st.form_submit_button("登録してメール認証を送信", use_container_width=True)

        if reg_submitted:
            # Validation
            if not all([reg_username, reg_email, reg_password, reg_password2]):
                st.error("全ての項目を入力してください")
            elif not validate_email_domain(reg_email):
                st.error(f"{_domains_display()} のメールアドレスのみ登録できます")
            elif len(reg_password) < 10:
                st.error("パスワードは10文字以上にしてください")
            elif not any(c.isdigit() for c in reg_password) or not any(c.isalpha() for c in reg_password):
                st.error("パスワードには英字と数字の両方を含めてください")
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
                    st.error("このメールアドレスまたは表示名は既に使用されています")
                else:
                    token = uuid.uuid4().hex
                    hashed = hash_password(reg_password)
                    db.execute(
                        """INSERT INTO users
                           (username, email, hashed_password, role, is_verified, verification_token, token_created_at)
                           VALUES (?, ?, ?, 'user', 0, ?, ?)""",
                        (reg_username, reg_email, hashed, token,
                         datetime.now(timezone.utc).isoformat()),
                    )
                    db.commit()
                    db.close()

                    if send_verification_email(reg_email, token):
                        st.success(
                            f"確認メールを {reg_email} に送信しました。\n"
                            f"メール内のリンクをクリックするか、認証コードを「認証コード入力」タブに入力してください。"
                        )
                    else:
                        st.warning("ユーザーは作成されましたが、確認メールの送信に失敗しました。管理者に連絡してください。")

    # --- 認証コード入力 ---
    with tab_verify:
        st.markdown("## 認証コード入力")
        st.info("確認メールに記載された認証コードを入力してください")

        with st.form("verify_form"):
            verify_token = st.text_input("認証コード", placeholder="メールに記載されたコードを入力")
            verify_submitted = st.form_submit_button("認証する", use_container_width=True)

        if verify_submitted and verify_token:
            verify_token = verify_token.strip()
            db = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE verification_token = ?", (verify_token,)
            ).fetchone()

            if not user:
                db.close()
                st.error("無効な認証コードです")
            else:
                token_time = datetime.fromisoformat(user["token_created_at"])
                if datetime.now(timezone.utc) - token_time > timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS):
                    db.close()
                    st.error("認証コードの有効期限が切れています。管理者に再送を依頼してください。")
                else:
                    db.execute(
                        "UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?",
                        (user["id"],),
                    )
                    db.commit()
                    db.close()
                    st.success(f"メールアドレス ({user['email']}) の認証が完了しました！「ログイン」タブからログインしてください。")


# ---------------------------------------------------------------------------
# App Pages
# ---------------------------------------------------------------------------
def page_generate():
    st.header("メルマガ生成")

    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY が設定されていません。管理者に連絡してください。")
        return

    db = get_db()
    files = db.execute("SELECT * FROM uploaded_files ORDER BY category, original_name").fetchall()
    db.close()

    selected_files = []
    if files:
        with st.expander("参考ファイルを選択（任意）", expanded=False):
            for cat_key, cat_label in ALLOWED_CATEGORIES.items():
                cat_files = [f for f in files if f["category"] == cat_key]
                if cat_files:
                    st.markdown(f"**{cat_label}**")
                    for f in cat_files:
                        if st.checkbox(f["original_name"], key=f"file_{f['id']}"):
                            selected_files.append(f"{f['category']}/{f['filename']}")

    with st.form("generate_form"):
        prompt = st.text_area(
            "作成指示",
            placeholder="例: 春の新商品キャンペーンのお知らせメルマガを作成してください",
            height=120,
        )
        col1, col2 = st.columns(2)
        with col1:
            tone = st.selectbox("トーン", ["professional", "casual", "friendly", "formal"], index=0)
        with col2:
            length = st.selectbox("長さ", ["short", "medium", "long"], index=1,
                                  format_func=lambda x: {"short": "短め", "medium": "標準", "long": "長め"}[x])
        submitted = st.form_submit_button("生成する", use_container_width=True)

    if submitted:
        if not prompt.strip():
            st.warning("作成指示を入力してください")
            return

        with st.spinner("メルマガを生成中..."):
            try:
                os.environ["ANTHROPIC_API_KEY"] = api_key
                os.environ["CLAUDE_MODEL"] = get_secret("CLAUDE_MODEL", "claude-sonnet-4-6")

                import asyncio
                result = asyncio.run(generate_newsletter(
                    prompt=prompt, tone=tone, length=length,
                    selected_files=selected_files if selected_files else None,
                ))
                st.session_state.generated_html = result["html"]
                st.session_state.generated_prompt = prompt
                st.session_state.tokens_used = result["tokens_used"]
            except Exception as e:
                st.error(f"生成エラー: {e}")
                return

    if "generated_html" in st.session_state:
        st.success(f"生成完了（トークン使用量: {st.session_state.tokens_used}）")

        tab_preview, tab_code = st.tabs(["プレビュー", "HTMLコード"])
        with tab_preview:
            st.components.v1.html(st.session_state.generated_html, height=600, scrolling=True)
        with tab_code:
            st.code(st.session_state.generated_html, language="html")

        with st.form("save_form"):
            title = st.text_input("タイトル", placeholder="メルマガのタイトルを入力")
            save_btn = st.form_submit_button("保存する")

        if save_btn and title.strip():
            db = get_db()
            db.execute(
                "INSERT INTO newsletters (title, html_content, prompt_used, created_by) VALUES (?, ?, ?, ?)",
                (title, st.session_state.generated_html, st.session_state.generated_prompt,
                 st.session_state.user["username"]),
            )
            db.commit()
            db.close()
            st.success("保存しました！")

        st.download_button(
            "HTMLファイルをダウンロード",
            st.session_state.generated_html,
            file_name="newsletter.html",
            mime="text/html",
        )


def page_history():
    st.header("生成履歴")
    db = get_db()
    newsletters = db.execute(
        "SELECT * FROM newsletters ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    db.close()

    if not newsletters:
        st.info("まだ履歴がありません")
        return

    for nl in newsletters:
        with st.expander(f"{nl['title']}（{nl['created_at']} / {nl['created_by']}）"):
            st.markdown(f"**プロンプト:** {nl['prompt_used']}")
            st.components.v1.html(nl["html_content"], height=400, scrolling=True)
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "HTMLダウンロード", nl["html_content"],
                    file_name=f"{nl['title']}.html", mime="text/html",
                    key=f"dl_{nl['id']}",
                )
            with col2:
                if is_admin():
                    if st.button("削除", key=f"del_{nl['id']}"):
                        db = get_db()
                        db.execute("DELETE FROM newsletters WHERE id = ?", (nl["id"],))
                        db.commit()
                        db.close()
                        st.rerun()


def page_files():
    st.header("ファイル管理")

    if is_admin():
        st.subheader("ファイルアップロード")
        with st.form("upload_form", clear_on_submit=True):
            category = st.selectbox(
                "カテゴリ", list(ALLOWED_CATEGORIES.keys()),
                format_func=lambda x: ALLOWED_CATEGORIES[x],
            )
            uploaded = st.file_uploader("ファイルを選択", type=["txt", "csv", "pdf", "text", "md"])
            upload_btn = st.form_submit_button("アップロード")

        if upload_btn and uploaded:
            content = uploaded.read()
            if len(content) > MAX_UPLOAD_SIZE:
                st.error("ファイルサイズが大きすぎます（最大 10MB）")
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

    st.subheader("アップロード済みファイル")
    db = get_db()
    files = db.execute("SELECT * FROM uploaded_files ORDER BY uploaded_at DESC").fetchall()
    db.close()

    if not files:
        st.info("ファイルがありません")
        return

    for cat_key, cat_label in ALLOWED_CATEGORIES.items():
        cat_files = [f for f in files if f["category"] == cat_key]
        if cat_files:
            st.markdown(f"### {cat_label}")
            for f in cat_files:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"{f['original_name']}（{f['uploaded_at']} / {f['uploaded_by']}）")
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


def page_users():
    if not is_admin():
        st.warning("管理者権限が必要です")
        return

    st.header("ユーザー管理")

    # --- 新規ユーザー追加（管理者による招待） ---
    with st.form("add_user_form", clear_on_submit=True):
        st.subheader("新規ユーザー招待")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_username = st.text_input("表示名")
        with col2:
            new_email = st.text_input("メールアドレス", placeholder=f"{_domains_display()}")
        with col3:
            new_role = st.selectbox("ロール", ["user", "admin"])
        new_password = st.text_input("初期パスワード（10文字以上・英数字必須）", type="password")
        add_btn = st.form_submit_button("追加して確認メールを送信")

    if add_btn:
        if not all([new_username, new_email, new_password]):
            st.error("全ての項目を入力してください")
        elif not validate_email_domain(new_email):
            st.error(f"{_domains_display()} のメールアドレスのみ登録できます")
        elif len(new_password) < 10:
            st.error("パスワードは10文字以上にしてください")
        elif not any(c.isdigit() for c in new_password) or not any(c.isalpha() for c in new_password):
            st.error("パスワードには英字と数字の両方を含めてください")
        else:
            new_email = new_email.strip().lower()
            db = get_db()
            existing = db.execute(
                "SELECT id FROM users WHERE email = ? OR username = ?",
                (new_email, new_username),
            ).fetchone()
            if existing:
                st.error("このメールアドレスまたは表示名は既に使用されています")
            else:
                token = uuid.uuid4().hex
                hashed = hash_password(new_password)
                db.execute(
                    """INSERT INTO users
                       (username, email, hashed_password, role, is_verified, verification_token, token_created_at)
                       VALUES (?, ?, ?, ?, 0, ?, ?)""",
                    (new_username, new_email, hashed, new_role, token,
                     datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
                db.close()

                if send_verification_email(new_email, token):
                    st.success(f"確認メールを {new_email} に送信しました")
                else:
                    st.warning("ユーザーは作成されましたが、確認メールの送信に失敗しました")

    # --- ユーザー一覧 ---
    st.subheader("ユーザー一覧")
    db = get_db()
    users = db.execute("SELECT id, username, email, role, is_verified, created_at FROM users ORDER BY id").fetchall()
    db.close()

    for u in users:
        verified_icon = "OK" if u["is_verified"] else "未認証"
        col1, col2, col3, col4, col5 = st.columns([2, 3, 1, 1, 1])
        with col1:
            st.text(u["username"])
        with col2:
            st.text(u["email"] or "-")
        with col3:
            st.text(u["role"])
        with col4:
            st.text(verified_icon)
        with col5:
            if u["username"] != "admin":
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if not u["is_verified"]:
                        if st.button("再送", key=f"resend_{u['id']}"):
                            token = uuid.uuid4().hex
                            db = get_db()
                            db.execute(
                                "UPDATE users SET verification_token = ?, token_created_at = ? WHERE id = ?",
                                (token, datetime.now(timezone.utc).isoformat(), u["id"]),
                            )
                            db.commit()
                            db.close()
                            if send_verification_email(u["email"], token):
                                st.success(f"確認メールを再送しました")
                            else:
                                st.error("再送に失敗しました")
                with btn_col2:
                    if st.button("削除", key=f"udel_{u['id']}"):
                        db = get_db()
                        db.execute("DELETE FROM users WHERE id = ?", (u["id"],))
                        db.commit()
                        db.close()
                        st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Newsletter AI",
        page_icon="📧",
        layout="wide",
    )

    init_db()
    require_login()

    with st.sidebar:
        st.markdown("### Newsletter AI")
        st.markdown(
            f"ログイン中: **{st.session_state.user['username']}**"
            f" ({st.session_state.user['email']})"
        )

        page = st.radio(
            "メニュー",
            ["メルマガ生成", "生成履歴", "ファイル管理"]
            + (["ユーザー管理"] if is_admin() else []),
            label_visibility="collapsed",
        )

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
    elif page == "ユーザー管理":
        page_users()


if __name__ == "__main__":
    main()
else:
    main()
