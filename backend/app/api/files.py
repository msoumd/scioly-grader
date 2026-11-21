"""Serve stored images to logged-in users (local storage; Supabase uses signed URLs)."""

from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.auth import GraderDep
from app.api.deps import get_storage
from app.api.errors import not_found
from app.services.storage import Storage, StorageError

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{key:path}", response_class=Response)
def get_file(
    key: str, grader: GraderDep, storage: Annotated[Storage, Depends(get_storage)]
) -> Response:
    try:
        data = storage.get(key)
    except StorageError as exc:
        raise not_found("File") from exc
    media = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=300"})
