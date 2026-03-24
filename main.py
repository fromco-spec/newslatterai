import os
import sys
import uuid
import shutil
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings
from database import init_db, get_db
from auth import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user,
    require_admin,
)
from ai_service import generate_newsletter

app = FastAPI(title=settings.APP_NAME)

BASE_DIR = os.path.dirname(__file__)
# Project layouts supported:
# - newsletter/frontend/index.html
# - newsletter/index.html (current repo layout)
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if not os.path.isdir(FRONTEND_DIR):
    FRONTEND_DIR = BASE_DIR
UPLOAD_DIR = settings.UPLOAD_DIR


# --- Models ---
class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class GenerateRequest(BaseModel):
    prompt: str
    tone: str = "professional"
    length: str = "medium"
    selected_files: list[str] | None = None


class SaveNewsletterRequest(BaseModel):
    title: str
    html_content: str
    prompt_used: str = ""


# --- Auth ---
@app.post("/api/auth/login")
def login(req: LoginRequest):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (req.username,)).fetchone()
    db.close()

    if not user or not verify_password(req.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="ユーザー名またはパスワードが正しくありません")

    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "role": user["role"], "username": user["username"]}


@app.get("/api/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


# --- User Management (Admin only) ---
@app.post("/api/users")
def create_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    if req.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username = ?", (req.username,)).fetchone()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="ユーザー名は既に使用されています")

    hashed = hash_password(req.password)
    db.execute(
        "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
        (req.username, hashed, req.role),
    )
    db.commit()
    db.close()
    return {"message": "ユーザーを作成しました"}


@app.get("/api/users")
def list_users(admin: dict = Depends(require_admin)):
    db = get_db()
    users = db.execute("SELECT id, username, role, created_at FROM users").fetchall()
    db.close()
    return [dict(u) for u in users]


@app.delete("/api/users/{username}")
def delete_user(username: str, admin: dict = Depends(require_admin)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="デフォルト管理者は削除できません")
    db = get_db()
    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    db.close()
    return {"message": "ユーザーを削除しました"}


# --- File Upload (Admin only) ---
ALLOWED_CATEGORIES = {"products", "instructions", "templates"}
ALLOWED_EXTENSIONS = {".txt", ".csv", ".pdf", ".text", ".md"}


@app.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    category: str = Form(...),
    admin: dict = Depends(require_admin),
):
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"許可されていないファイル形式です: {ext}")

    # Check file size
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="ファイルサイズが大きすぎます (最大10MB)")

    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    category_dir = os.path.join(UPLOAD_DIR, category)
    os.makedirs(category_dir, exist_ok=True)
    filepath = os.path.join(category_dir, safe_filename)

    with open(filepath, "wb") as f:
        f.write(content)

    db = get_db()
    db.execute(
        "INSERT INTO uploaded_files (filename, category, original_name, uploaded_by) VALUES (?, ?, ?, ?)",
        (safe_filename, category, file.filename, admin["username"]),
    )
    db.commit()
    db.close()

    return {"message": "アップロード完了", "filename": safe_filename}


@app.get("/api/files")
def list_files(
    category: str = None,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    if category:
        files = db.execute(
            "SELECT * FROM uploaded_files WHERE category = ? ORDER BY uploaded_at DESC",
            (category,),
        ).fetchall()
    else:
        files = db.execute(
            "SELECT * FROM uploaded_files ORDER BY uploaded_at DESC"
        ).fetchall()
    db.close()
    return [dict(f) for f in files]


@app.delete("/api/files/{file_id}")
def delete_file(file_id: int, admin: dict = Depends(require_admin)):
    db = get_db()
    file_record = db.execute("SELECT * FROM uploaded_files WHERE id = ?", (file_id,)).fetchone()
    if not file_record:
        db.close()
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    filepath = os.path.join(UPLOAD_DIR, file_record["category"], file_record["filename"])
    if os.path.exists(filepath):
        os.remove(filepath)

    db.execute("DELETE FROM uploaded_files WHERE id = ?", (file_id,))
    db.commit()
    db.close()
    return {"message": "ファイルを削除しました"}


# --- Newsletter Generation ---
@app.post("/api/newsletter/generate")
async def generate(req: GenerateRequest, current_user: dict = Depends(get_current_user)):
    try:
        result = await generate_newsletter(
            prompt=req.prompt,
            tone=req.tone,
            length=req.length,
            selected_files=req.selected_files,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成エラー: {str(e)}")


@app.post("/api/newsletter/save")
def save_newsletter(req: SaveNewsletterRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    db.execute(
        "INSERT INTO newsletters (title, html_content, prompt_used, created_by) VALUES (?, ?, ?, ?)",
        (req.title, req.html_content, req.prompt_used, current_user["username"]),
    )
    db.commit()
    db.close()
    return {"message": "保存しました"}


@app.get("/api/newsletter/history")
def get_history(current_user: dict = Depends(get_current_user)):
    db = get_db()
    newsletters = db.execute(
        "SELECT * FROM newsletters ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    db.close()
    return [dict(n) for n in newsletters]


@app.get("/api/newsletter/{newsletter_id}")
def get_newsletter(newsletter_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    newsletter = db.execute(
        "SELECT * FROM newsletters WHERE id = ?", (newsletter_id,)
    ).fetchone()
    db.close()
    if not newsletter:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(newsletter)


@app.delete("/api/newsletter/{newsletter_id}")
def delete_newsletter(newsletter_id: int, admin: dict = Depends(require_admin)):
    db = get_db()
    db.execute("DELETE FROM newsletters WHERE id = ?", (newsletter_id,))
    db.commit()
    db.close()
    return {"message": "削除しました"}


# --- Static files ---
# Serve static assets if a dedicated directory exists.
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# --- Startup ---
@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
