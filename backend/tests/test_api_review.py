"""Review-screen support: team crop, unknown teams, discard reasons, re-open, history."""

from fastapi.testclient import TestClient

from tests.api_support import AP_FILE, TEAMS_CSV, all_correct, login, sheet_jpeg

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _setup(api: TestClient) -> None:
    login(api, "Supervisor", admin=True)
    api.post("/api/events/import", files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)})
    api.post("/api/teams/import", files={"file": ("teams.csv", TEAMS_CSV, "text/csv")})
    api.post("/api/logout")


def _upload(api: TestClient, jpeg: bytes) -> dict:  # type: ignore[type-arg]
    r = api.post(
        "/api/scans", data={"event_code": "AP"}, files={"file": ("p.jpg", jpeg, "image/jpeg")}
    )
    (created,) = r.json()["scans"]
    return api.get(f"/api/scans/{created['id']}").json()  # type: ignore[no-any-return]


def test_team_crop_is_viewable_and_storage_key_is_not_exposed(api: TestClient) -> None:
    _setup(api)
    login(api)
    scan = _upload(api, sheet_jpeg(all_correct(), [[0], [1]], seed=1))
    assert scan["team_crop_url"]
    crop = api.get(scan["team_crop_url"])
    assert crop.status_code == 200 and crop.headers["content-type"] == "image/png"
    assert "crop" not in scan["team"]


def test_unknown_team_counts_only_after_explicit_acknowledgement(api: TestClient) -> None:
    _setup(api)
    login(api, "Alice")
    scan = _upload(api, sheet_jpeg(all_correct(), [[9], [9]], seed=3))
    assert scan["team_number"] == 99 and "team_unknown" in scan["flags"]
    assert scan["status"] == "needs_review"

    r = api.post(f"/api/scans/{scan['id']}/confirm")
    assert r.status_code == 409 and r.json()["code"] == "team_unknown"
    r = api.post(f"/api/scans/{scan['id']}/confirm", json={"accept_unknown_team": True})
    assert r.status_code == 200 and r.json()["is_counted"]
    history = api.get(f"/api/scans/{scan['id']}/history").json()
    assert ("accepted_unknown_team", "99", "Alice") in {
        (h["field"], h["new_value"], h["grader"]) for h in history
    }


def test_discard_records_the_reason(api: TestClient) -> None:
    _setup(api)
    login(api, "Alice")
    scan = _upload(api, sheet_jpeg({}, [[], []], seed=4))
    r = api.post(f"/api/scans/{scan['id']}/discard", json={"reason": "  blurry,   retaken "})
    assert r.json()["status"] == "discarded" and r.json()["discard_reason"] == "blurry, retaken"
    plain = _upload(api, sheet_jpeg({}, [[], []], seed=5))
    assert api.post(f"/api/scans/{plain['id']}/discard").json()["discard_reason"] is None


def test_reopen_is_admin_only_uncounts_and_is_audited(api: TestClient) -> None:
    _setup(api)
    login(api, "Alice")
    scan = _upload(api, sheet_jpeg(all_correct(), [[0], [2]], seed=2))
    assert scan["status"] == "confirmed" and scan["is_counted"]
    r = api.post(f"/api/scans/{scan['id']}/reopen")
    assert r.status_code == 403 and r.json()["code"] == "admin_only"

    api.post("/api/logout")
    login(api, "Supervisor", admin=True)
    opened = api.post(f"/api/scans/{scan['id']}/reopen").json()
    assert opened["status"] == "needs_review" and not opened["is_counted"]
    assert "reopened" in opened["flags"]
    again = api.post(f"/api/scans/{scan['id']}/reopen")
    assert again.status_code == 409 and again.json()["code"] == "not_confirmed"

    fixed = api.patch(f"/api/scans/{scan['id']}", json={"marks": {"1": ["A"]}}).json()
    assert fixed["mcq_score"] == "59.00"
    assert api.post(f"/api/scans/{scan['id']}/confirm").json()["is_counted"]
    fields = [(h["field"], h["grader"]) for h in api.get(f"/api/scans/{scan['id']}/history").json()]
    assert ("status", "Supervisor") in fields and ("q1", "Supervisor") in fields


def test_history_needs_login_and_a_real_scan(api: TestClient) -> None:
    assert api.get("/api/scans/1/history").status_code == 401
    login(api)
    assert api.get("/api/scans/999/history").json()["code"] == "not_found"
