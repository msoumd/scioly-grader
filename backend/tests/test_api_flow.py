"""The whole tournament flow over HTTP, checked against a hand calculation.

Teams and what they bubbled (A&P key; questions 11 and 14 are worth 2 points):
  team 1: every answer right                      -> 60
  team 2: questions 1-10 right, rest blank        -> 10   (q1-q10 are 1 point each)
  team 3: nothing bubbled                         ->  0
  team 4: q11 = D and q14 = B (both right)        ->  4
  team 5: q1 = D right, forgot the team digits    ->  1 after a grader sets team 5
Free response (out of 140): 1 -> 100, 2 -> 50.5, 4 -> 10, 5 -> 20, 3 -> not entered.
Totals: 1 = 160, 2 = 60.5, 5 = 21, 4 = 14, 3 = 0 (missing free response).
"""

import csv
import io

from fastapi.testclient import TestClient

from tests.api_support import AP_FILE, TEAMS_CSV, all_correct, ap_setup, login, sheet_jpeg

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload(api: TestClient, jpeg: bytes, name: str = "photo.jpg") -> dict:  # type: ignore[type-arg]
    r = api.post(
        "/api/scans", data={"event_code": "AP"}, files={"file": (name, jpeg, "image/jpeg")}
    )
    assert r.status_code == 202, r.text
    (created,) = r.json()["scans"]
    scan = api.get(f"/api/scans/{created['id']}").json()
    assert scan["status"] != "processing"
    return scan


def test_full_tournament_flow(api: TestClient) -> None:
    # --- supervisor sets up
    login(api, "Supervisor", admin=True)
    preview = api.post(
        "/api/events/import?dry_run=true",
        files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)},
    )
    assert preview.status_code == 200 and preview.json()["saved"] is False
    assert preview.json()["report"]["question_count"] == 54
    assert api.get("/api/events").json() == []

    r = api.post("/api/events/import", files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)})
    assert r.json()["saved"] and r.json()["action"] == "created" and r.json()["event_code"] == "AP"
    r = api.post("/api/teams/import", files={"file": ("teams.csv", TEAMS_CSV, "text/csv")})
    assert r.json()["ok"] and r.json()["inserted"] == 5
    sheet = api.get("/api/events/AP/sheet.pdf")
    assert sheet.headers["content-type"] == "application/pdf" and sheet.content[:5] == b"%PDF-"
    api.post("/api/logout")

    # --- a grader scores
    login(api, "Alice")
    assert api.put("/api/events/AP/teams/1/free-response", json={"value": 100}).status_code == 200

    key = {q.q: list(q.correct) for q in ap_setup().questions}
    s1 = _upload(api, sheet_jpeg(all_correct(), [[0], [1]], seed=1))
    s2 = _upload(api, sheet_jpeg({q: key[q] for q in range(1, 11)}, [[0], [2]], seed=2))
    s3 = _upload(api, sheet_jpeg({}, [[0], [3]], seed=3))
    s4 = _upload(api, sheet_jpeg({11: ["D"], 14: ["B"]}, [[0], [4]], seed=4))
    s5 = _upload(api, sheet_jpeg({1: ["D"]}, [[], []], seed=5))

    for scan, team, score in [(s1, 1, "60.00"), (s2, 2, "10.00"), (s3, 3, "0.00"), (s4, 4, "4.00")]:
        assert scan["status"] == "confirmed" and scan["is_counted"], scan["flags"]
        assert (scan["team_number"], scan["mcq_score"]) == (team, score)
        assert scan["flags"] == [] and scan["grader"] == "Alice"
    assert s5["status"] == "needs_review" and not s5["is_counted"]
    assert s5["team_number"] is None and "team_digit_missing" in s5["flags"]
    assert s5["mcq_score"] == "1.00"
    assert api.get(s5["original_url"]).status_code == 200  # original kept and viewable
    assert api.get(s5["warped_url"]).headers["content-type"] == "image/png"

    pending = api.get("/api/events/AP/scans?status=needs_review").json()
    assert [s["id"] for s in pending] == [s5["id"]]

    # Confirming without a team number is refused; fix it, then confirm.
    r = api.post(f"/api/scans/{s5['id']}/confirm")
    assert r.status_code == 409 and r.json()["code"] == "team_missing"
    fixed = api.patch(f"/api/scans/{s5['id']}", json={"team_number": 5}).json()
    assert fixed["team_number"] == 5 and fixed["status"] == "needs_review"
    done = api.post(f"/api/scans/{s5['id']}/confirm").json()
    assert done["status"] == "confirmed" and done["is_counted"]

    for team, value in [(2, 50.5), (4, 10), (5, 20)]:
        assert (
            api.put(f"/api/events/AP/teams/{team}/free-response", json={"value": value}).status_code
            == 200
        )

    # --- results match the hand calculation
    res = api.get("/api/events/AP/results").json()
    got = [
        (r["rank"], r["team_number"], r["mcq"], r["free_response"], r["total"], r["missing"])
        for r in res["rows"]
    ]
    assert got == [
        (1, 1, "60.00", "100.0", "160.00", []),
        (2, 2, "10.00", "50.5", "60.50", []),
        (3, 5, "1.00", "20.0", "21.00", []),
        (4, 4, "4.00", "10.0", "14.00", []),
        (5, 3, "0.00", None, "0.00", ["free_response"]),
    ]
    assert res["teams_complete"] == 4 and res["scans_needing_review"] == 0
    assert res["rows"][0]["mcq_by"] == "Alice" and res["rows"][0]["free_response_by"] == "Alice"

    rows = list(csv.DictReader(io.StringIO(api.get("/api/events/AP/results.csv").text)))
    assert [(r["rank"], r["team_number"], r["team_name"], r["total"]) for r in rows] == [
        ("1", "1", "Alpha HS", "160"),
        ("2", "2", "Beta MS", "60.5"),
        ("3", "5", "Epsilon", "21"),
        ("4", "4", "Delta HS", "14"),
        ("5", "3", "Gamma Acad", "0"),
    ]
    assert rows[4]["missing"] == "free_response"

    # --- every edit is in the audit log, with who did it
    api.post("/api/logout")
    login(api, "Supervisor", admin=True)
    trail = api.get(f"/api/audit?entity=scan&entity_id={s5['id']}").json()
    fields = {(a["field"], a["old_value"], a["new_value"], a["grader"]) for a in trail}
    assert ("team_number", None, "5", "Alice") in fields
    assert ("status", "needs_review", "confirmed", "Alice") in fields
    events = api.get("/api/events").json()
    assert events[0]["scans_counted"] == 5 and events[0]["scans_needing_review"] == 0
