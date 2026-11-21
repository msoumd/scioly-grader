import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import make_engine

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "migrated_engine" in metafunc.fixturenames:
        params = ["sqlite"] + (["postgres"] if os.environ.get("TEST_POSTGRES_URL") else [])
        metafunc.parametrize("migrated_engine", params, indirect=True)


def _alembic_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture
def migrated_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    """Fresh database at Alembic head, on SQLite and (if configured) Postgres."""
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'test.db'}"
    else:
        url = os.environ["TEST_POSTGRES_URL"]
    cfg = _alembic_cfg(url)
    if request.param == "postgres":
        command.downgrade(cfg, "base")  # start clean if a previous run died
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    yield engine
    engine.dispose()
    command.downgrade(cfg, "base")


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def api(migrated_engine: Engine, tmp_path: Path) -> Iterator["TestClient"]:
    """A test client for the full app on a fresh database (SQLite and Postgres).
    Reads run inside the request so results are ready immediately."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.storage import LocalStorage
    from tests.api_support import settings_for

    settings = settings_for(tmp_path)
    app = create_app(settings, migrated_engine, LocalStorage(settings.upload_dir))
    with TestClient(app, base_url="https://testserver") as client:
        yield client
