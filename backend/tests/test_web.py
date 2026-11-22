"""The built phone app is served from the API's origin, with an SPA fallback."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from app.services.storage import LocalStorage
from tests.api_support import settings_for


def _client(tmp_path: Path, engine: Engine, dist: str) -> TestClient:
    settings = settings_for(tmp_path, frontend_dist=dist)
    return TestClient(create_app(settings, engine, LocalStorage(settings.upload_dir)))


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "sw.js").write_text("// sw")
    (tmp_path / "secret.txt").write_text("outside dist")
    return dist


def test_serves_app_with_spa_fallback(tmp_path: Path, migrated_engine: Engine) -> None:
    c = _client(tmp_path, migrated_engine, str(_dist(tmp_path)))
    root = c.get("/")
    assert root.status_code == 200 and "<title>app</title>" in root.text
    assert root.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in root.headers["content-security-policy"]
    deep = c.get("/scan/whatever")
    assert deep.status_code == 200 and "<title>app</title>" in deep.text

    asset = c.get("/assets/index-abc123.js")
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    assert c.get("/sw.js").headers["cache-control"] == "no-cache"


def test_api_paths_are_not_swallowed(tmp_path: Path, migrated_engine: Engine) -> None:
    c = _client(tmp_path, migrated_engine, str(_dist(tmp_path)))
    assert c.get("/health").json()["status"] == "ok"
    missing = c.get("/api/nope")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert c.get("/api/me").json()["code"] == "not_logged_in"
    assert c.get("/openapi.json").json()["info"]["title"] == "scioly-grader"


def test_no_files_outside_dist(tmp_path: Path, migrated_engine: Engine) -> None:
    c = _client(tmp_path, migrated_engine, str(_dist(tmp_path)))
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        r = c.get(path)
        assert "outside dist" not in r.text


def test_api_only_without_a_build(tmp_path: Path, migrated_engine: Engine) -> None:
    c = _client(tmp_path, migrated_engine, str(tmp_path / "no-build"))
    assert c.get("/").status_code == 404
    assert c.get("/health").status_code == 200
