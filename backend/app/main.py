"""FastAPI app. ``create_app`` takes settings, an engine and storage so tests (and
scripts) can build an app around their own database; ``app`` is the production one."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api import auth, events, files, results, scans, teams
from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.config import DEV_SECRET, Settings, get_settings
from app.db.session import make_engine
from app.services.reading import ReadingQueue
from app.services.storage import Storage, make_storage

log = logging.getLogger("scioly")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=()",
}


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    storage: Storage | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)
    storage = storage or make_storage(settings)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if settings.session_secret == DEV_SECRET:
        log.warning("SESSION_SECRET is the development default; set it before deploying")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            app.state.reading_queue.recover_stuck()
        except Exception:  # a fresh database without tables must not stop startup
            log.exception("could not check for stuck scans")
        yield
        app.state.reading_queue.shutdown()

    app = FastAPI(
        title="scioly-grader",
        version="0.5.0",
        description="Science Olympiad bubble-sheet grader. Log in with `POST /api/login` "
        "first; the session cookie is then sent automatically from this page.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.sessionmaker = sessions
    app.state.storage = storage
    app.state.reading_queue = ReadingQueue(sessions, storage, settings)
    app.state.login_limiter = auth.LoginLimiter(
        settings.login_attempts_per_window, settings.login_window_seconds
    )

    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_id_and_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        log.info(
            "%s %s %s %d %.0fms",
            rid,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    app.include_router(health_router)
    for module in (auth, events, teams, scans, results, files):
        app.include_router(module.router)
    return app


app = create_app()
