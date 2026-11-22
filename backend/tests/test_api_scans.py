"""Scan rules over HTTP: duplicates, corrections, re-scoring, uploads, failures."""

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.db.models import Scan
from app.main import create_app
from app.services.storage import LocalStorage
from tests.api_support import AP_FILE, TEAMS_CSV, all_correct, login, settings_for, sheet_jpeg

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _setup_event(api: TestClient) -> None:
    login(api, "Supervisor", admin=True)
    assert api.post(
        "/api/events/import", files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)}
    ).json()["saved"]
    assert api.post("/api/teams/import", files={"file": ("t.csv", TEAMS_CSV, "text/csv")}).json()[
        "ok"
    ]


def _upload(
    api: TestClient, data: bytes, name: str = "p.jpg", mime: str = "image/jpeg", event: str = "AP"
) -> list[dict]:  # type: ignore[type-arg]
    r = api.post("/api/scans", data={"event_code": event}, files={"file": (name, data, mime)})
    assert r.status_code == 202, r.text
    return [api.get(f"/api/scans/{s['id']}").json() for s in r.json()["scans"]]


def test_duplicate_scans_and_supervisor_choice(api: TestClient) -> None:
    _setup_event(api)
    (first,) = _upload(api, sheet_jpeg({1: ["D"]}, [[0], [1]], seed=1))
    (second,) = _upload(api, sheet_jpeg(all_correct(), [[0], [1]], seed=2))
    assert first["is_counted"] and first["status"] == "confirmed"
    assert second["status"] == "needs_review" and "duplicate_team" in second["flags"]

    r = api.post(f"/api/scans/{second['id']}/confirm")
    assert r.status_code == 409 and r.json()["code"] == "duplicate_team"
    assert r.json()["other_scan_id"] == first["id"]

    dups = api.get("/api/events/AP/duplicates").json()
    assert [(d["team_number"], [s["id"] for s in d["scans"]]) for d in dups] == [
        (1, [first["id"], second["id"]])
    ]
    chosen = api.post("/api/events/AP/teams/1/counted-scan", json={"scan_id": second["id"]}).json()
    assert chosen["is_counted"] and chosen["status"] == "confirmed"
    assert "duplicate_team" not in chosen["flags"]
    assert api.get(f"/api/scans/{first['id']}").json()["status"] == "discarded"
    assert api.get("/api/events/AP/duplicates").json() == []
    row = api.get("/api/events/AP/results").json()["rows"][0]
    assert (row["team_number"], row["mcq"]) == (1, "60.00")

    wrong = api.post("/api/events/AP/teams/2/counted-scan", json={"scan_id": second["id"]})
    assert wrong.status_code == 422 and wrong.json()["code"] == "wrong_scan"


def test_corrections_rescore_and_audit(api: TestClient) -> None:
    _setup_event(api)
    (scan,) = _upload(api, sheet_jpeg({1: ["D"], 2: ["A"]}, [[0], [2]]))  # q2 key is C
    assert scan["mcq_score"] == "1.00" and scan["is_counted"]
    fixed = api.patch(f"/api/scans/{scan['id']}", json={"marks": {"2": ["c"]}}).json()
    q2 = next(q for q in fixed["questions"] if q["q"] == 2)
    assert q2 == {**q2, "marked": ["C"], "detected": ["A"], "corrected": True}
    assert fixed["mcq_score"] == "2.00" and fixed["is_counted"]
    trail = {
        (a["field"], a["old_value"], a["new_value"])
        for a in api.get(f"/api/audit?entity=scan&entity_id={scan['id']}").json()
    }
    assert ("q2", "A", "C") in trail and ("mcq_score", "1.00", "2.00") in trail

    # Changing a counted scan's team un-counts it until it is confirmed again
    moved = api.patch(f"/api/scans/{scan['id']}", json={"team_number": 3}).json()
    assert (moved["team_number"], moved["is_counted"], moved["status"]) == (
        3,
        False,
        "needs_review",
    )
    assert api.post(f"/api/scans/{scan['id']}/confirm").json()["is_counted"]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"marks": {"2": ["F"]}}, "bad_letter"),
        ({"marks": {"99": ["A"]}}, "unknown_question"),
        ({"team_number": -1}, "bad_team"),
    ],
)
def test_correction_validation(api: TestClient, body: dict, code: str) -> None:  # type: ignore[type-arg]
    _setup_event(api)
    (scan,) = _upload(api, sheet_jpeg({1: ["D"]}, [[0], [2]]))
    r = api.patch(f"/api/scans/{scan['id']}", json=body)
    assert r.status_code == 422 and r.json()["code"] == code


def test_unknown_team_number_needs_review(api: TestClient) -> None:
    _setup_event(api)
    (scan,) = _upload(api, sheet_jpeg({1: ["D"]}, [[9], [9]]))
    assert scan["team_number"] == 99 and "team_unknown" in scan["flags"]
    r = api.post(f"/api/scans/{scan['id']}/confirm")
    assert r.status_code == 409 and r.json()["code"] == "team_unknown"


def test_discard_never_counts(api: TestClient) -> None:
    _setup_event(api)
    (scan,) = _upload(api, sheet_jpeg({1: ["D"]}, [[0], [4]]))
    gone = api.post(f"/api/scans/{scan['id']}/discard").json()
    assert (gone["status"], gone["is_counted"]) == ("discarded", False)
    assert api.post(f"/api/scans/{scan['id']}/confirm").json()["code"] == "discarded"
    row = next(r for r in api.get("/api/events/AP/results").json()["rows"] if r["team_number"] == 4)
    assert row["mcq"] is None and row["rank"] is None


def test_rescore_after_key_change(api: TestClient, tmp_path: Path) -> None:
    _setup_event(api)
    (scan,) = _upload(api, sheet_jpeg({1: ["A"]}, [[0], [1]]))  # q1 key D: 0 points
    assert scan["mcq_score"] == "0.00"
    wb = load_workbook(AP_FILE)
    for row in wb["Event"].iter_rows(min_row=2):
        if row[0].value == "sheet_version":
            row[1].value = 2
    wb["Questions"]["D2"] = "A"  # key fix: q1 is A
    path = tmp_path / "ap_v2.xlsx"
    wb.save(path)
    same = load_workbook(AP_FILE)
    same["Questions"]["D2"] = "A"
    same_path = tmp_path / "ap_same_version.xlsx"
    same.save(same_path)

    locked = api.post(
        "/api/events/import", files={"file": ("a.xlsx", same_path.read_bytes(), XLSX)}
    )
    assert locked.status_code == 409 and locked.json()["code"] == "event_locked"
    r = api.post("/api/events/import", files={"file": ("a.xlsx", path.read_bytes(), XLSX)})
    assert r.json()["action"] == "new_version"
    preview = api.post("/api/events/AP/rescore?dry_run=true").json()
    assert preview == {"changed": 1, "saved": False}
    assert api.post("/api/events/AP/rescore?dry_run=true").json()["changed"] == 1  # not saved
    assert api.post("/api/events/AP/rescore").json() == {"changed": 1, "saved": True}
    assert api.post("/api/events/AP/rescore").json()["changed"] == 0
    assert api.get(f"/api/scans/{scan['id']}").json()["mcq_score"] == "1.00"
    assert api.post("/api/events/AP/rescore").json() == {"changed": 0, "saved": True}


def test_multipage_pdf_upload(api: TestClient) -> None:
    _setup_event(api)
    pages = [
        Image.open(io.BytesIO(sheet_jpeg({1: ["D"]}, [[0], [t]], seed=t))).convert("RGB")
        for t in (1, 2, 3)
    ]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    scans = _upload(api, buf.getvalue(), "batch.pdf", "application/pdf")
    assert [(s["page"], s["team_number"], s["is_counted"]) for s in scans] == [
        (1, 1, True),
        (2, 2, True),
        (3, 3, True),
    ]
    assert len({s["original_url"] for s in scans}) == 1  # one original PDF, kept once


def test_unreadable_photo_asks_for_retake(api: TestClient) -> None:
    _setup_event(api)
    blank = np.full((1200, 900, 3), 230, np.uint8)
    buf = io.BytesIO()
    Image.fromarray(blank).save(buf, "JPEG")
    (scan,) = _upload(api, buf.getvalue())
    assert scan["status"] == "needs_review" and "retake" in scan["flags"]
    assert scan["mcq_score"] is None
    r = api.post(f"/api/scans/{scan['id']}/confirm")
    assert r.status_code == 409 and r.json()["code"] == "unreadable"


def test_corrupt_image_marks_scan_failed(api: TestClient) -> None:
    _setup_event(api)
    (scan,) = _upload(api, b"\xff\xd8\xff" + b"garbage" * 50)
    assert scan["status"] == "failed" and scan["error"]
    r = api.patch(f"/api/scans/{scan['id']}", json={"team_number": 1})
    assert r.status_code == 409 and r.json()["code"] == "not_ready"


@pytest.mark.parametrize(
    ("name", "data", "mime", "status", "code"),
    [
        ("x.gif", b"GIF89a....", "image/gif", 415, "unsupported_type"),
        ("x.jpg", b"<html>not a photo</html>", "image/jpeg", 415, "unsupported_type"),
        ("x.jpg", b"", "image/jpeg", 400, "empty_file"),
        ("x.pdf", b"%PDF-1.4 truncated", "application/pdf", 415, "unreadable_pdf"),
    ],
)
def test_upload_rejections(
    api: TestClient, name: str, data: bytes, mime: str, status: int, code: str
) -> None:
    _setup_event(api)
    r = api.post("/api/scans", data={"event_code": "AP"}, files={"file": (name, data, mime)})
    assert r.status_code == status and r.json()["code"] == code


def test_upload_unknown_event(api: TestClient) -> None:
    _setup_event(api)
    r = api.post(
        "/api/scans",
        data={"event_code": "NOPE"},
        files={"file": ("p.jpg", sheet_jpeg({}, [[0], [1]]), "image/jpeg")},
    )
    assert r.status_code == 404


def test_upload_size_limit(migrated_engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(tmp_path, max_upload_mb=1)
    app = create_app(settings, migrated_engine, LocalStorage(settings.upload_dir))
    with TestClient(app, base_url="https://testserver") as api:
        _setup_event(api)
        big = b"\xff\xd8\xff" + b"0" * (1024 * 1024 + 10)
        r = api.post(
            "/api/scans", data={"event_code": "AP"}, files={"file": ("b.jpg", big, "image/jpeg")}
        )
        assert r.status_code == 413 and r.json()["code"] == "too_large"


@pytest.mark.parametrize(
    "key", ["../../etc/passwd", "uploads/../../secret", "%2e%2e/x", "/etc/passwd"]
)
def test_files_route_rejects_traversal(api: TestClient, key: str) -> None:
    login(api)
    assert api.get(f"/api/files/{key}").status_code == 404


def test_background_reading_and_stuck_recovery(migrated_engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(tmp_path, reader_sync=False, reader_workers=2)
    app = create_app(settings, migrated_engine, LocalStorage(settings.upload_dir))
    with TestClient(app, base_url="https://testserver") as api:
        _setup_event(api)
        r = api.post(
            "/api/scans",
            data={"event_code": "AP"},
            files={"file": ("p.jpg", sheet_jpeg({1: ["D"]}, [[0], [1]]), "image/jpeg")},
        )
        assert r.json()["scans"][0]["status"] == "processing"
        app.state.reading_queue.wait()
        scan_id = r.json()["scans"][0]["id"]
        assert api.get(f"/api/scans/{scan_id}").json()["status"] == "confirmed"

        # Simulate a crash mid-read: put it back to processing, long ago.
        with Session(migrated_engine) as db:
            db.execute(
                update(Scan)
                .where(Scan.id == scan_id)
                .values(
                    status="processing",
                    is_counted=False,
                    updated_at=datetime.now(UTC) - timedelta(minutes=10),
                )
            )
            db.commit()
        assert app.state.reading_queue.recover_stuck() == 1
        app.state.reading_queue.wait()
        assert api.get(f"/api/scans/{scan_id}").json()["status"] == "confirmed"
        assert app.state.reading_queue.recover_stuck() == 0


def test_free_response_rules(api: TestClient) -> None:
    _setup_event(api)
    put = lambda team, v: api.put(f"/api/events/AP/teams/{team}/free-response", json={"value": v})  # noqa: E731
    assert put(1, 140).status_code == 200
    assert put(1, 140.5).json()["code"] == "over_max"
    assert put(1, 10.25).json()["code"] == "half_points"
    assert put(1, -1).json()["code"] == "validation_error"
    assert put(77, 10).status_code == 404
    assert put(1, 99.5).json()["value"] == "99.5"
    trail = api.get("/api/audit?entity=free_response_score").json()
    assert [(a["old_value"], a["new_value"]) for a in trail] == [("140.0", "99.5"), (None, "140")]


def test_event_import_errors(api: TestClient) -> None:
    login(api, "Supervisor", admin=True)
    bad = (Path(__file__).parent / "fixtures" / "event_setup" / "many_problems.xlsx").read_bytes()
    r = api.post("/api/events/import", files={"file": ("bad.xlsx", bad, XLSX)}).json()
    assert r["saved"] is False and len(r["report"]["errors"]) == 3
    assert "Questions row 2 (q 1)" in r["report"]["text"]
    r = api.post("/api/events/import", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    assert api.get("/api/events/NOPE").status_code == 404
    bad_csv = api.post(
        "/api/teams/import", files={"file": ("t.csv", b"team_number,team_name\nx,A\n", "text/csv")}
    ).json()
    assert bad_csv["ok"] is False and bad_csv["inserted"] == 0


def test_event_detail_and_lists(api: TestClient) -> None:
    _setup_event(api)
    detail = api.get("/api/events/AP").json()
    assert detail["question_count"] == 54 and detail["mcq_points_total"] == "60.00"
    assert detail["questions"][8] == {**detail["questions"][8], "q": 9, "correct": ["C", "D"]}
    assert [t["team_number"] for t in api.get("/api/teams").json()] == [1, 2, 3, 4, 5]
