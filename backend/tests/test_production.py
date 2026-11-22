"""Production refuses laptop defaults; HTTPS gets HSTS; /docs is off in production."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import DEV_SECRET, Settings
from app.main import create_app
from app.services.storage import LocalStorage
from tests.api_support import settings_for

GOOD_PROD = {
    "environment": "production",
    "database_url": "postgresql+psycopg://u:p@db.example/x",
    "session_secret": "s" * 48,
    "tournament_pin": "2468",
    "admin_pin": "135799",
    "cookie_secure": True,
    "storage_backend": "supabase",
    "supabase_url": "https://abc.supabase.co",
    "supabase_service_role_key": "service-role-key-for-tests",
    "frontend_dist": "off",
}


def test_safe_production_settings_have_no_problems() -> None:
    assert Settings(**GOOD_PROD).production_problems() == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"session_secret": DEV_SECRET}, "SESSION_SECRET"),
        ({"session_secret": "short"}, "SESSION_SECRET"),
        ({"tournament_pin": "change-me"}, "TOURNAMENT_PIN"),
        ({"admin_pin": None}, "ADMIN_PIN must be set"),
        ({"admin_pin": "2468xx", "tournament_pin": "2468xx"}, "must differ"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"database_url": "sqlite:///./x.db"}, "Postgres"),
        ({"storage_backend": "local"}, "STORAGE_BACKEND"),
        ({"supabase_service_role_key": None}, "SUPABASE_SERVICE_ROLE_KEY"),
    ],
)
def test_unsafe_production_settings_refuse_to_start(change: dict, problem: str) -> None:  # type: ignore[type-arg]
    settings = Settings(**{**GOOD_PROD, **change})
    assert any(problem in p for p in settings.production_problems())
    with pytest.raises(RuntimeError, match="Unsafe production settings"):
        create_app(settings)


def test_development_defaults_are_allowed() -> None:
    assert Settings(environment="development").production_problems() == []


@pytest.mark.parametrize("url", ["postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"])
def test_provider_database_urls_get_the_psycopg_driver(url: str) -> None:
    assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/db"


def test_docs_off_in_production_on_in_development(tmp_path: Path, migrated_engine: Engine) -> None:
    prod = Settings(**{**GOOD_PROD, "upload_dir": str(tmp_path)})
    app = create_app(prod, migrated_engine, LocalStorage(tmp_path))
    with TestClient(app, base_url="https://grader.example") as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        r = c.get("/health")
        assert r.json()["status"] == "ok"
        assert r.headers["strict-transport-security"].startswith("max-age=31536000")
    dev = settings_for(tmp_path)
    with TestClient(create_app(dev, migrated_engine, LocalStorage(tmp_path))) as c:
        assert c.get("/docs").status_code == 200
        assert "strict-transport-security" not in c.get("/health").headers  # plain http


def test_health_reports_deployed_commit(
    tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123")
    app = create_app(settings_for(tmp_path), migrated_engine, LocalStorage(tmp_path))
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok", "commit": "0123456789ab"}
