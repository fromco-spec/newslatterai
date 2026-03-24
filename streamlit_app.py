"""
Newsletter AI - Streamlit App
社内向けメルマガ生成ツール（セキュアなチーム共有版）
"""

import os
import uuid
import sqlite3
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

import streamlit as st
from passlib.context import CryptContext

from ai_service import generate_newsletter, read_file_content

# ---------------------------------------------------------------------------
# セキュリティ定数
# ---------------------------------------------------------------------------
MAX_LOGIN_ATTEMPTS = 5          # 最大ログイン試行回数
LOGIN_LOCKOUT_SECONDS = 300     # ロックアウト時間（5分）
SESSION_TIMEOUT_MINUTES = 60    # セッションタイムアウト（60分）

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_CATEGORIES = {"products": "商品情報", "instructions": "指示書", "templates": "テンプレート"}
ALLOWED_EXTENSIONS = {".txt", ".csv", ".pdf", ".text", ".md"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_secret(key: str, default: str = "") -> str:
    """st.secrets → 環境変数 → デフォルトの優先順位で取得"""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.environ.get(key, default)


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
            hashed_password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
    # Default admin
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if c.fetchone()[0] == 0:
        pw = get_secret("ADMIN_DEFAULT_PASSWORD", "admin1234")
        hashed = pwd_context.hash(pw)
        c.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
            ("admin", hashed, "admin"),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def authenticate(username: str, password: str) -> dict | None:
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    db.close()
    if user and pwd_context.verify(password, user["hashed_password"]):
        return {"username": user["username"], "role": user["role"]}
    return None


def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        show_login()
        st.stop()

    # セッションタイムアウト判定
    last = st.session_state.get("last_activity", 0)
    if last and (time.time() - last) > SESSION_TIMEOUT_MINUTES * 60:
        st.session_state.clear()
        st.warning("セッションがタイムアウトしました。再度ログインしてください。")
        st.stop()

    # アクティビティ更新
    st.session_state.last_activity = time.time()


def is_admin() -> bool:
    return st.session_state.get("user", {}).get("role") == "admin"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _check_login_lockout() -> bool:
    """ログイン試行回数をチェックし、ロックアウト中なら True を返す"""
    attempts = st.session_state.get("login_attempts", 0)
    locked_until = st.session_state.get("login_locked_until", 0)

    if locked_until and time.time() < locked_until:
        remaining = int(locked_until - time.time())
        st.error(f"ログイン試行回数が上限に達しました。{remaining}秒後に再試行してください。")
        return True

    # ロックアウト期間が終わっていたらリセット
    if locked_until and time.time() >= locked_until:
        st.session_state.login_attempts = 0
        st.session_state.login_locked_until = 0

    return False


def _record_failed_login():
    """失敗回数を記録し、上限に達したらロックアウト"""
    attempts = st.session_state.get("login_attempts", 0) + 1
    st.session_state.login_attempts = attempts
    if attempts >= MAX_LOGIN_ATTEMPTS:
        st.session_state.login_locked_until = time.time() + LOGIN_LOCKOUT_SECONDS


def show_login():
    st.markdown("## Newsletter AI にログイン")

    if _check_login_lockout():
        return

    with st.form("login_form"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン", use_container_width=True)

    if submitted:
        if not username or not password:
            st.error("ユーザー名とパスワードを入力してください")
            return
        user = authenticate(username, password)
        if user:
            st.session_state.login_attempts = 0
            st.session_state.login_locked_until = 0
            st.session_state.user = user
            st.session_state.last_activity = time.time()
            st.rerun()
        else:
            _record_failed_login()
            remaining = MAX_LOGIN_ATTEMPTS - st.session_state.get("login_attempts", 0)
            if remaining > 0:
                st.error(f"ユーザー名またはパスワードが正しくありません（残り{remaining}回）")
            else:
                st.error(f"ログイン試行回数の上限に達しました。{LOGIN_LOCKOUT_SECONDS // 60}分間ロックされます。")


def page_generate():
    st.header("メルマガ生成")

    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY が設定されていません。管理者に連絡してください。")
        return

    # File selection
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
                # Temporarily set env for ai_service
                os.environ["ANTHROPIC_API_KEY"] = api_key
                os.environ["CLAUDE_MODEL"] = get_secret("CLAUDE_MODEL", "claude-sonnet-4-6")

                import asyncio
                result = asyncio.run(generate_newsletter(
                    prompt=prompt,
                    tone=tone,
                    length=length,
                    selected_files=selected_files if selected_files else None,
                ))

                st.session_state.generated_html = result["html"]
                st.session_state.generated_prompt = prompt
                st.session_state.tokens_used = result["tokens_used"]
            except Exception as e:
                st.error(f"生成エラー: {e}")
                return

    # Show result
    if "generated_html" in st.session_state:
        st.success(f"生成完了（トークン使用量: {st.session_state.tokens_used}）")

        tab_preview, tab_code = st.tabs(["プレビュー", "HTMLコード"])
        with tab_preview:
            st.components.v1.html(st.session_state.generated_html, height=600, scrolling=True)
        with tab_code:
            st.code(st.session_state.generated_html, language="html")

        # Save
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

        # Download
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
                    "HTMLダウンロード",
                    nl["html_content"],
                    file_name=f"{nl['title']}.html",
                    mime="text/html",
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
                "カテゴリ",
                list(ALLOWED_CATEGORIES.keys()),
                format_func=lambda x: ALLOWED_CATEGORIES[x],
            )
            uploaded = st.file_uploader(
                "ファイルを選択",
                type=["txt", "csv", "pdf", "text", "md"],
            )
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

    with st.form("add_user_form", clear_on_submit=True):
        st.subheader("新規ユーザー追加")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_username = st.text_input("ユーザー名")
        with col2:
            new_password = st.text_input("パスワード", type="password")
        with col3:
            new_role = st.selectbox("ロール", ["user", "admin"])
        add_btn = st.form_submit_button("追加")

    if add_btn:
        if not new_username or not new_password:
            st.error("ユーザー名とパスワードを入力してください")
        elif len(new_password) < 10:
            st.error("パスワードは10文字以上にしてください")
        elif not any(c.isdigit() for c in new_password) or not any(c.isalpha() for c in new_password):
            st.error("パスワードには英字と数字の両方を含めてください")
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE username = ?", (new_username,)).fetchone()
            if existing:
                st.error("そのユーザー名は既に使用されています")
            else:
                hashed = pwd_context.hash(new_password)
                db.execute(
                    "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
                    (new_username, hashed, new_role),
                )
                db.commit()
                st.success(f"ユーザー「{new_username}」を追加しました")
            db.close()

    st.subheader("ユーザー一覧")
    db = get_db()
    users = db.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
    db.close()

    for u in users:
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            st.text(u["username"])
        with col2:
            st.text(u["role"])
        with col3:
            if u["username"] != "admin":
                if st.button("削除", key=f"udel_{u['id']}"):
                    db = get_db()
                    db.execute("DELETE FROM users WHERE username = ?", (u["username"],))
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

    # Sidebar
    with st.sidebar:
        st.markdown(f"### Newsletter AI")
        st.markdown(f"ログイン中: **{st.session_state.user['username']}** ({st.session_state.user['role']})")

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

    # Routing
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
