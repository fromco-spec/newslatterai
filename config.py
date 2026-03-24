import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Newsletter AI App"
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ANTHROPIC_API_KEY: str = ""
    # Set via .env. Keep a safe default for local dev.
    CLAUDE_MODEL: str = "claude-3-5-sonnet-latest"
    DATABASE_URL: str = "sqlite:///./data/app.db"
    UPLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "uploads")
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB

    class Config:
        # Keep all runtime config inside this project folder.
        env_file = os.path.join(os.path.dirname(__file__), ".env")


settings = Settings()

if not settings.SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY が未設定です。.env ファイルに SECRET_KEY を設定してください。\n"
        "生成例: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )
