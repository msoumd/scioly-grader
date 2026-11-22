import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check for the host and uptime monitors. ``commit`` is the deployed git
    commit (set by Render) so the deploy workflow can tell when a new version is live."""
    commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or ""
    return {"status": "ok", "commit": commit[:12]}
