"""Reading uploads safely: size limit while reading, and type checks by content."""

from __future__ import annotations

from fastapi import UploadFile

from app.api.errors import ApiError

CHUNK = 1 << 20

# Accepted scan uploads, recognised by their first bytes (never by the filename).
_SIGNATURES: tuple[tuple[str, bytes, int], ...] = (
    (".jpg", b"\xff\xd8\xff", 0),
    (".png", b"\x89PNG\r\n\x1a\n", 0),
    (".pdf", b"%PDF-", 0),
    (".heic", b"ftypheic", 4),
    (".heic", b"ftypheix", 4),
    (".heic", b"ftypmif1", 4),
    (".heic", b"ftypmsf1", 4),
    (".heic", b"ftyphevc", 4),
)
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".heic": "image/heic",
}


async def read_limited(file: UploadFile, max_mb: int) -> bytes:
    limit = max_mb * 1024 * 1024
    chunks, size = [], 0
    while chunk := await file.read(CHUNK):
        size += len(chunk)
        if size > limit:
            raise ApiError(413, "too_large", f"File is larger than {max_mb} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ApiError(400, "empty_file", "The uploaded file is empty")
    return data


def scan_kind(data: bytes) -> str:
    """File extension for an accepted scan upload, or a 415 error."""
    for ext, magic, offset in _SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            return ext
    raise ApiError(415, "unsupported_type", "Upload a photo (JPEG, PNG, HEIC) or a PDF")
