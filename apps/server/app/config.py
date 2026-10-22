"""全局配置：路径、端口、数据目录。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "天健湖"
APP_SLUG = "tianjianhu"
VERSION = "0.2.0"

BASE_DIR = Path(__file__).resolve().parent.parent      # apps/server
PROJECT_DIR = BASE_DIR.parent.parent                   # 仓库根目录
LEGACY_DATA_DIR = BASE_DIR / "data"                    # v0.2.0 之前的旧位置


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TJH_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = PROJECT_DIR / "data"
    web_dist: Path = PROJECT_DIR / "apps" / "web" / "dist"
    cors_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    max_workers: int = 4
    log_level: str = "INFO"

    # —— 账号与会话 ——
    session_cookie: str = "tjh_session"
    session_days: int = 30
    cookie_secure: bool = False          # 放到 HTTPS 后面时置为 true
    allow_registration: bool = True       # 首次安装的默认值，之后以数据库设置为准
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    password_min_length: int = 8

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.uploads_dir, self.cache_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
