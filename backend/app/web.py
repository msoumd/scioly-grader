"""Serve the built phone app (``frontend/dist``) from the API's own origin.

One origin means one HTTPS certificate, no CORS, and the login cookie just works. Paths
that are files in ``dist`` are served as they are; any other non-API path gets
``index.html`` so the app can handle it. ``/api/...`` paths that don't exist stay JSON 404s.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.errors import not_found

RESERVED = ("api/", "docs", "redoc", "openapi.json", "health")

# The app itself only talks to this origin; images can come from signed storage links.
CSP = (
    "default-src 'self'; "
    "img-src 'self' blob: data: https:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
NO_CACHE = {"Cache-Control": "no-cache"}
FOREVER = {"Cache-Control": "public, max-age=31536000, immutable"}


def default_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """Add the catch-all route serving ``dist``. Returns False if there is no build."""
    index = dist / "index.html"
    if not index.is_file():
        return False
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(RESERVED):
            raise not_found("Page")
        if path:
            file = (root / path).resolve()
            if file.is_relative_to(root) and file.is_file():
                hashed = file.parent.name == "assets"  # Vite names these by content hash
                return FileResponse(file, headers=FOREVER if hashed else NO_CACHE)
        return FileResponse(index, headers={**NO_CACHE, "Content-Security-Policy": CSP})

    return True
