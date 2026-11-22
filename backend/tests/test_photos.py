"""Photos are deleted once a sheet is counted or discarded; marks, scores and history stay."""

import io
import json
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine

from app.main import create_app
from app.services.storage import LocalStorage, SupabaseStorage
from tests.api_support import AP_FILE, TEAMS_CSV, all_correct, login, settings_for, sheet_jpeg

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _app(tmp_path: Path, engine: Engine, storage: object = None, **overrides: object):  # type: ignore[no-untyped-def]
    settings = settings_for(tmp_path, **overrides)
    store = storage or LocalStorage(settings.upload_dir)
    return create_app(settings, engine, store), Path(settings.upload_dir)  # type: ignore[arg-type]


def _setup(c: TestClient) -> None:
    login(c, "Supervisor", admin=True)
    c.post("/api/events/import", files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)})
    c.post("/api/teams/import", files={"file": ("teams.csv", TEAMS_CSV, "text/csv")})


def _upload(c: TestClient, data: bytes, name: str = "p.jpg", kind: str = "image/jpeg") -> list:  # type: ignore[type-arg]
    r = c.post("/api/scans", data={"event_code": "AP"}, files={"file": (name, data, kind)})
    assert r.status_code == 202, r.text
    return [c.get(f"/api/scans/{s['id']}").json() for s in r.json()["scans"]]


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_auto_counted_sheet_keeps_score_but_not_photos(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    app, root = _app(tmp_path, migrated_engine)
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        (scan,) = _upload(c, sheet_jpeg(all_correct(), [[0], [1]], seed=1))
        assert scan["status"] == "confirmed" and scan["mcq_score"] == "60.00"
        assert scan["photos_deleted"] and scan["original_url"] is None
        assert scan["warped_url"] is None and scan["team_crop_url"] is None
        assert scan["questions"] and all(q["crop_url"] is None for q in scan["questions"])
        assert _files(root) == []
        # Re-scoring and results still work from the saved marks.
        assert c.post("/api/events/AP/rescore").json()["changed"] == 0
        row = c.get("/api/events/AP/results").json()["rows"][0]
        assert row["team_number"] == 1 and row["mcq"] == "60.00"


def test_review_sheet_keeps_photos_until_confirmed_then_deletes(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    app, root = _app(tmp_path, migrated_engine)
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        (scan,) = _upload(c, sheet_jpeg(all_correct(), [[], []], seed=2))  # no team number
        assert scan["status"] == "needs_review" and not scan["photos_deleted"]
        assert c.get(scan["original_url"]).status_code == 200
        assert c.get(scan["team_crop_url"]).status_code == 200
        assert len(_files(root)) >= 3  # original, straightened page, team crop
        c.patch(f"/api/scans/{scan['id']}", json={"team_number": 2})
        done = c.post(f"/api/scans/{scan['id']}/confirm").json()
        assert done["is_counted"] and done["photos_deleted"] and done["original_url"] is None
        assert _files(root) == []
        history = c.get(f"/api/scans/{scan['id']}/history").json()
        assert any(h["field"] == "team_number" for h in history)  # history stays


def test_discard_deletes_photos(tmp_path: Path, migrated_engine: Engine) -> None:
    app, root = _app(tmp_path, migrated_engine)
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        (scan,) = _upload(c, sheet_jpeg({}, [[], []], seed=3))
        assert _files(root)
        assert c.post(f"/api/scans/{scan['id']}/discard").json()["photos_deleted"]
        assert _files(root) == []


def test_pdf_original_is_kept_until_every_page_is_done(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    app, root = _app(tmp_path, migrated_engine)
    pages = [
        Image.open(io.BytesIO(sheet_jpeg(all_correct(), team, seed=s))).convert("RGB")
        for team, s in [([[0], [3]], 4), ([[], []], 5)]
    ]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        first, second = _upload(c, buf.getvalue(), "two.pdf", "application/pdf")
        assert first["status"] == "confirmed" and first["photos_deleted"]
        assert second["status"] == "needs_review"
        assert any(f.endswith("original.pdf") for f in _files(root))  # page 2 still needs it
        assert c.get(second["original_url"]).status_code == 200
        c.patch(f"/api/scans/{second['id']}", json={"team_number": 4})
        c.post(f"/api/scans/{second['id']}/confirm")
        assert _files(root) == []


def test_duplicate_choice_deletes_photos_of_both(tmp_path: Path, migrated_engine: Engine) -> None:
    app, root = _app(tmp_path, migrated_engine)
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        _upload(c, sheet_jpeg(all_correct(), [[0], [5]], seed=6))
        (dup,) = _upload(c, sheet_jpeg({1: ["D"]}, [[0], [5]], seed=7))
        assert "duplicate_team" in dup["flags"] and _files(root)
        r = c.post("/api/events/AP/teams/5/counted-scan", json={"scan_id": dup["id"]})
        assert r.json()["photos_deleted"]
        assert _files(root) == []


class FlakyStorage(LocalStorage):
    """Storage whose deletes fail until switched back on."""

    down = True

    def delete(self, keys: list[str]) -> None:
        if self.down:
            raise OSError("storage unreachable")
        super().delete(keys)


def test_failed_deletes_are_retried_by_the_sweep(tmp_path: Path, migrated_engine: Engine) -> None:
    store = FlakyStorage(tmp_path / "up")
    app, _ = _app(tmp_path, migrated_engine, store, upload_dir=str(tmp_path / "up"))
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        (scan,) = _upload(c, sheet_jpeg(all_correct(), [[0], [1]], seed=1))
        assert scan["status"] == "confirmed" and not scan["photos_deleted"]  # still counts
        store.down = False
        assert app.state.reading_queue.sweep_photos() == 1
        assert c.get(f"/api/scans/{scan['id']}").json()["photos_deleted"]
        assert _files(tmp_path / "up") == []


def test_can_be_switched_off(tmp_path: Path, migrated_engine: Engine) -> None:
    app, root = _app(tmp_path, migrated_engine, delete_photos_when_done=False)
    with TestClient(app, base_url="https://t") as c:
        _setup(c)
        (scan,) = _upload(c, sheet_jpeg(all_correct(), [[0], [1]], seed=1))
        assert scan["status"] == "confirmed" and not scan["photos_deleted"]
        assert c.get(scan["original_url"]).status_code == 200


@respx.mock
def test_supabase_delete_call() -> None:
    route = respx.delete("https://proj.supabase.co/storage/v1/object/scans").mock(
        return_value=httpx.Response(200, json=[])
    )
    store = SupabaseStorage("https://proj.supabase.co", "service-key", "scans", 600)
    store.delete(["uploads/a/original.jpg", "scans/1/warped.png"])
    sent = route.calls.last.request
    assert json.loads(sent.content) == {
        "prefixes": ["uploads/a/original.jpg", "scans/1/warped.png"]
    }
    assert sent.headers["authorization"] == "Bearer service-key"
    store.delete([])  # nothing to do, no call
    assert route.call_count == 1


def test_local_delete_tidies_empty_folders(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path)
    store.put("scans/9/warped.png", b"x", "image/png")
    store.put("scans/9/crop_1.png", b"x", "image/png")
    store.delete(["scans/9/warped.png", "scans/9/crop_1.png", "scans/9/missing.png"])
    assert list(tmp_path.iterdir()) == []
