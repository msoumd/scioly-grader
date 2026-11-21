"""Storage backends (Supabase mocked over HTTP) and ranking rules."""

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from app.config import Settings
from app.services.results import Row, rank
from app.services.storage import LocalStorage, StorageError, SupabaseStorage, make_storage


def test_local_storage_round_trip(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path)
    store.put("uploads/abc/original.jpg", b"jpeg", "image/jpeg")
    assert store.get("uploads/abc/original.jpg") == b"jpeg"
    assert store.url("uploads/abc/original.jpg") == "/api/files/uploads/abc/original.jpg"
    assert not list(tmp_path.rglob("*.part"))
    with pytest.raises(StorageError):
        store.get("uploads/missing.jpg")


@pytest.mark.parametrize("key", ["../x", "a/../../x", "/abs", "a//b", "", "a\\b", "x" * 300])
def test_storage_keys_cannot_escape(tmp_path: Path, key: str) -> None:
    with pytest.raises(StorageError):
        LocalStorage(tmp_path).put(key, b"x", "text/plain")


BASE = "https://proj.supabase.co"


@respx.mock
def test_supabase_storage_calls() -> None:
    up = respx.post(f"{BASE}/storage/v1/object/scans/uploads/a/original.jpg").mock(
        return_value=httpx.Response(200, json={"Key": "scans/uploads/a/original.jpg"})
    )
    down = respx.get(f"{BASE}/storage/v1/object/scans/uploads/a/original.jpg").mock(
        return_value=httpx.Response(200, content=b"jpeg")
    )
    sign = respx.post(f"{BASE}/storage/v1/object/sign/scans/uploads/a/original.jpg").mock(
        return_value=httpx.Response(
            200, json={"signedURL": "/object/sign/scans/uploads/a/original.jpg?token=t"}
        )
    )
    store = SupabaseStorage(BASE, "service-key", "scans", 600)

    store.put("uploads/a/original.jpg", b"jpeg", "image/jpeg")
    sent = up.calls.last.request
    assert sent.headers["authorization"] == "Bearer service-key"
    assert sent.headers["apikey"] == "service-key"
    assert sent.headers["x-upsert"] == "true" and sent.headers["content-type"] == "image/jpeg"
    assert sent.content == b"jpeg"

    assert store.get("uploads/a/original.jpg") == b"jpeg"
    assert down.called
    url = store.url("uploads/a/original.jpg")
    assert url == f"{BASE}/storage/v1/object/sign/scans/uploads/a/original.jpg?token=t"
    assert sign.calls.last.request.read() == b'{"expiresIn":600}'


@respx.mock
def test_supabase_errors_raise() -> None:
    respx.post(f"{BASE}/storage/v1/object/scans/k.jpg").mock(return_value=httpx.Response(403))
    respx.get(f"{BASE}/storage/v1/object/scans/k.jpg").mock(return_value=httpx.Response(404))
    store = SupabaseStorage(BASE, "key", "scans", 60)
    with pytest.raises(StorageError, match="upload failed"):
        store.put("k.jpg", b"x", "image/jpeg")
    with pytest.raises(StorageError, match="download failed"):
        store.get("k.jpg")


def test_make_storage(tmp_path: Path) -> None:
    assert isinstance(make_storage(Settings(upload_dir=str(tmp_path))), LocalStorage)
    with pytest.raises(StorageError, match="SUPABASE_URL"):
        make_storage(Settings(storage_backend="supabase"))
    s = make_storage(
        Settings(storage_backend="supabase", supabase_url=BASE, supabase_service_role_key="k")
    )
    assert isinstance(s, SupabaseStorage)


def _row(team: int, mcq: str | None, fr: str | None) -> Row:
    return Row(
        team_number=team,
        team_name=str(team),
        mcq=Decimal(mcq) if mcq is not None else None,
        free_response=Decimal(fr) if fr is not None else None,
        mcq_by=None,
        mcq_at=None,
        fr_by=None,
        fr_at=None,
        waiting_review=False,
    )


def test_ties_share_a_rank() -> None:
    rows = [
        _row(1, "50", "10"),
        _row(2, "40", "20"),
        _row(3, "55", "0"),
        _row(4, "10", None),
        _row(5, None, None),
        _row(6, "0", None),
    ]
    rank(rows)
    assert [(r.team_number, r.rank) for r in rows] == [
        (1, 1),
        (2, 1),
        (3, 3),
        (4, 4),
        (5, None),
        (6, 5),
    ]
    assert _row(6, "0", None).missing == ["free_response"]
    assert _row(5, None, None).total == Decimal("0.00")
