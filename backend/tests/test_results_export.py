"""Results table and CSV export: totals only when complete, ties, missing parts, golden CSV,
free-response edits and their history, teams dry run."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Event, FreeResponseScore, Grader, Scan, ScanStatus
from app.services.event_import import import_event_workbook
from app.services.event_store import save_event
from app.services.results import results, results_csv
from app.services.teams_import import parse_teams_csv, save_teams
from tests.api_support import AP_FILE, TEAMS_CSV, login

GOLDEN = Path(__file__).parent / "golden" / "results_AP.csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
T0 = datetime(2026, 11, 21, 14, 3, 5)
T1 = datetime(2026, 11, 21, 15, 30, 0)


def _fixture(db: Session) -> Event:
    """Six teams: a tie for first, a team with no scan, one with no free response, one with
    nothing, and a name with accents (Excel must show it right)."""
    setup = import_event_workbook(AP_FILE).setup
    assert setup is not None
    save_event(db, setup, AP_FILE.name)
    teams = (
        "team_number,team_name\n1,Alpha HS\n2,Beta MS\n3,Gamma Acad\n"
        "4,Délta Escuela\n5,Epsilon\n6,Zeta\n"
    )
    save_teams(db, parse_teams_csv(teams.encode()).teams)
    alice, bo = Grader(name="Alice"), Grader(name="Bo Chen")
    db.add_all([alice, bo])
    db.flush()
    event = db.query(Event).one()
    for team, mcq in [(1, "50"), (2, "40.5"), (3, "55"), (5, "10")]:
        db.add(
            Scan(
                event_id=event.id,
                team_number=team,
                sheet_version=1,
                image_path=f"uploads/{team}.jpg",
                mcq_score=Decimal(mcq),
                status=ScanStatus.confirmed,
                is_counted=True,
                grader_id=alice.id,
                created_at=T0,
                updated_at=T0,
            )
        )
    for team, fr in [(1, "10"), (2, "19.5"), (3, "0"), (4, "33")]:
        db.add(
            FreeResponseScore(
                event_id=event.id,
                team_number=team,
                value=Decimal(fr),
                grader_id=bo.id,
                created_at=T1,
                updated_at=T1,
            )
        )
    db.commit()
    return event


def test_results_rank_complete_teams_only_with_shared_ranks(db: Session) -> None:
    rows = results(db, _fixture(db))
    got = [(r.rank, r.team_number, r.total, r.missing) for r in rows]
    assert got == [
        (1, 1, Decimal("60"), []),
        (1, 2, Decimal("60.0"), []),
        (3, 3, Decimal("55"), []),
        (None, 4, None, ["multiple_choice"]),
        (None, 5, None, ["free_response"]),
        (None, 6, None, ["multiple_choice", "free_response"]),
    ]


def test_csv_matches_golden_file(db: Session) -> None:
    text = results_csv(results(db, _fixture(db)))
    assert text.startswith("﻿")
    assert text.encode("utf-8") == GOLDEN.read_bytes(), "regenerate only if the change is intended"


def _setup_api(api: TestClient) -> None:
    login(api, "Supervisor", admin=True)
    api.post("/api/events/import", files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)})
    api.post("/api/teams/import", files={"file": ("teams.csv", TEAMS_CSV, "text/csv")})
    api.post("/api/logout")


def test_free_response_rules_edits_and_history(api: TestClient) -> None:
    _setup_api(api)
    login(api, "Alice")
    put = lambda team, v: api.put(f"/api/events/AP/teams/{team}/free-response", json={"value": v})  # noqa: E731
    assert put(1, 140.5).json()["code"] == "over_max"
    assert put(1, 10.25).json()["code"] == "half_points"
    assert put(1, -1).json()["code"] == "validation_error"
    assert put(99, 10).json()["code"] == "not_found"
    assert put(1, 12.5).status_code == 200
    api.post("/api/logout")
    login(api, "Bo")
    assert put(1, 13).json()["grader"] == "Bo"

    history = api.get("/api/events/AP/teams/1/free-response/history").json()
    assert [(h["old_value"], h["new_value"], h["grader"]) for h in history] == [
        (None, "12.5", "Alice"),
        ("12.5", "13", "Bo"),
    ]
    assert api.get("/api/events/AP/teams/2/free-response/history").json() == []
    res = api.get("/api/events/AP/results").json()
    row = next(r for r in res["rows"] if r["team_number"] == 1)
    assert row["free_response"] == "13.0" and row["free_response_by"] == "Bo"
    assert row["total"] is None and row["rank"] is None and row["missing"] == ["multiple_choice"]
    assert res["teams_without_scan"] == 5 and res["teams_without_free_response"] == 4


def test_csv_download_headers(api: TestClient) -> None:
    _setup_api(api)
    login(api)
    r = api.get("/api/events/AP/results.csv")
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert 'filename="AP_results.csv"' in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")


def test_teams_dry_run_reports_without_saving(api: TestClient) -> None:
    login(api, "Supervisor", admin=True)
    csv_data = b"team_number,team_name\n1,Alpha\n2,Beta\n"
    preview = api.post(
        "/api/teams/import?dry_run=true", files={"file": ("t.csv", csv_data, "text/csv")}
    ).json()
    assert preview["ok"] and preview["inserted"] == 2 and preview["saved"] is False
    assert api.get("/api/teams").json() == []
    saved = api.post("/api/teams/import", files={"file": ("t.csv", csv_data, "text/csv")}).json()
    assert saved["saved"] and saved["inserted"] == 2
    assert len(api.get("/api/teams").json()) == 2
