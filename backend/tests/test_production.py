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
    "tournament_pin": "246810",
    "admin_pin": "13579135",
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
        ({"tournament_pin": "2468"}, "TOURNAMENT_PIN"),
        ({"admin_pin": "135799"}, "ADMIN_PIN must be set"),
        ({"admin_pin": "2468xxxx", "tournament_pin": "2468xxxx"}, "must differ"),
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
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "fedcba9876543210")
        assert c.get("/health").json()["commit"] == "fedcba987654"


def test_client_ip_trusts_only_the_proxies_hops() -> None:
    from starlette.requests import Request

    from app.api.auth import client_ip

    def req(*xff: str) -> Request:
        headers = [(b"x-forwarded-for", v.encode()) for v in xff]
        return Request({"type": "http", "headers": headers, "client": ("10.0.0.1", 5)})

    # Caller-written entries on the left are ignored; the proxy's entry on the right counts.
    assert client_ip(req("6.6.6.6, 203.0.113.9"), 1) == "203.0.113.9"
    assert client_ip(req("1.1.1.1", "2.2.2.2, 203.0.113.9"), 1) == "203.0.113.9"
    assert client_ip(req("6.6.6.6, 203.0.113.9, 10.1.1.1"), 2) == "203.0.113.9"
    assert client_ip(req("6.6.6.6"), 0) == "10.0.0.1"  # not behind a proxy: header ignored
    assert client_ip(req(), 1) == "10.0.0.1"


def test_wrong_pins_from_changing_ips_hit_the_site_wide_limit() -> None:
    from app.api.auth import LoginLimiter

    lim = LoginLimiter(attempts=10, window_s=300, all_attempts=5)
    for i in range(5):
        assert not lim.blocked(f"10.0.0.{i}")
        lim.fail(f"10.0.0.{i}")
    assert lim.blocked("10.9.9.9")  # a brand-new IP is blocked too


def test_spoofed_forwarded_for_does_not_escape_the_pin_limit(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    settings = settings_for(tmp_path, trusted_proxy_hops=1, login_attempts_per_window=3)
    app = create_app(settings, migrated_engine, LocalStorage(tmp_path))
    with TestClient(app) as c:
        codes = []
        for i in range(5):
            # The attacker invents a new "IP" each time; the proxy appends the real one.
            headers = {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.7"}
            r = c.post("/api/login", json={"pin": "0000", "grader_name": "x"}, headers=headers)
            codes.append(r.json()["code"])
        assert codes == ["wrong_pin"] * 3 + ["too_many_attempts"] * 2


def test_every_table_has_row_level_security_on_postgres(migrated_engine: Engine) -> None:
    """Supabase's REST API must not see any table (RLS on, no policies)."""
    if migrated_engine.dialect.name != "postgresql":
        pytest.skip("Postgres only")
    from sqlalchemy import text

    with migrated_engine.connect() as conn:
        open_tables = (
            conn.execute(
                text(
                    "select c.relname from pg_class c "
                    "join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = 'public' and c.relkind = 'r' "
                    "and not c.relrowsecurity"
                )
            )
            .scalars()
            .all()
        )
    assert open_tables == []
