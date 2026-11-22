from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-session-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "production" refuses to start with development defaults (see production_problems).
    environment: Literal["development", "production"] = "development"
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
    enable_docs: bool | None = None  # the /docs page; default: on in development only
    sentry_dsn: str | None = None  # error reports (optional)
    cors_origins: list[str] = []
    # Built phone app to serve at "/": "" = the repo's frontend/dist if it was built,
    # "off" = API only.
    frontend_dist: str = ""

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        """Hosting providers hand out postgres:// URLs; SQLAlchemy needs the psycopg driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v.removeprefix(prefix)
        return v

    @property
    def docs_enabled(self) -> bool:
        return self.enable_docs if self.enable_docs is not None else not self.is_production

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_problems(self) -> list[str]:
        """Settings that are fine on a laptop but unsafe on the internet."""
        if not self.is_production:
            return []
        problems = []
        if self.session_secret == DEV_SECRET or len(self.session_secret) < 32:
            problems.append("SESSION_SECRET must be a long random value (32+ characters)")
        if self.tournament_pin in ("change-me", "") or len(self.tournament_pin) < 4:
            problems.append("TOURNAMENT_PIN must be set (4+ characters)")
        if not self.admin_pin or len(self.admin_pin) < 6:
            problems.append("ADMIN_PIN must be set (6+ characters)")
        if self.admin_pin and self.admin_pin == self.tournament_pin:
            problems.append("ADMIN_PIN must differ from TOURNAMENT_PIN")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (HTTPS only)")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must point at Postgres (SQLite is lost on redeploy)")
        if self.storage_backend != "supabase":
            problems.append("STORAGE_BACKEND must be supabase (local files are lost on redeploy)")
        elif not (self.supabase_url and self.supabase_service_role_key):
            problems.append("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return problems

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
