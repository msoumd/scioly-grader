"""Request dependencies. Everything comes from ``app.state`` so tests can build an app
with their own database, settings and storage (see ``app.main.create_app``)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings

if TYPE_CHECKING:
    from app.services.reading import ReadingQueue
    from app.services.storage import Storage


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def get_queue(request: Request) -> ReadingQueue:
    queue: ReadingQueue = request.app.state.reading_queue
    return queue
