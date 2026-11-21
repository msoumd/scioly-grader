from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-session-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scioly.db"

    # --- login: graders type the shared PIN plus their name; the admin PIN unlocks
    # supervisor actions (import events/teams, choose between duplicate scans, re-score).
    tournament_pin: str = "change-me"
    admin_pin: str | None = None
    session_secret: str = DEV_SECRET  # signs login cookies; set a long random value in prod
    session_hours: int = 18  # one tournament day
    cookie_secure: bool = True  # cookies only over HTTPS (set false only for plain-http dev)
    login_attempts_per_window: int = 10
    login_window_seconds: int = 300

    # --- storage of uploaded images
    storage_backend: Literal["local", "supabase"] = "local"
    upload_dir: str = "./data/uploads"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None  # server-side only, never sent to clients
    supabase_bucket: str = "scans"
    signed_url_seconds: int = 600

    # --- uploads and reading
    max_upload_mb: int = 25
    reader_workers: int = 2
    reader_sync: bool = False  # read during the request (tests); otherwise in a thread pool
    stuck_after_seconds: int = 120  # scans still "processing" this long are retried

    # --- web
    cors_origins: list[str] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
