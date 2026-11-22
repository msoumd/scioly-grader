from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# One web process serves every phone: up to ~40 request threads plus the readers. A
# request holds a connection only for its own queries, so 10 + 20 overflow is plenty
# (Supabase's pooler allows far more).
POOL = {"pool_size": 10, "max_overflow": 20, "pool_timeout": 30}


def make_engine(url: str) -> Engine:
    if url == "sqlite://" or ":memory:" in url:
        return create_engine(url, connect_args={"check_same_thread": False})
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False}, **POOL)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    # Supabase transaction pooler (port 6543) does not support prepared statements.
    return create_engine(url, pool_pre_ping=True, connect_args={"prepare_threshold": None}, **POOL)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
