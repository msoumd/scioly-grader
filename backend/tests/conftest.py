import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import make_engine

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
