from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event, Team
from app.schemas.event_setup import TeamRow
from app.services.teams_import import import_teams_csv, parse_teams_csv, save_teams


def test_plain_csv() -> None:
    report = parse_teams_csv(b"team_number,team_name\n1,Alpha HS\n2,Beta MS\n")
    assert report.ok
    assert [(t.team_number, t.team_name) for t in report.teams] == [(1, "Alpha HS"), (2, "Beta MS")]


def test_bom_and_whitespace_and_crlf() -> None:
    data = "﻿Team_Number , team_name \r\n 7 ,  Gamma Academy \r\n\r\n12,Delta\r\n"
    report = parse_teams_csv(data.encode("utf-8"))
    assert report.ok, report.errors
    assert [(t.team_number, t.team_name) for t in report.teams] == [
        (7, "Gamma Academy"),
        (12, "Delta"),
    ]


def test_quoted_names_with_commas() -> None:
    report = parse_teams_csv(b'team_number,team_name\n3,"Smith, Jones & Co. HS"\n')
    assert report.teams[0].team_name == "Smith, Jones & Co. HS"


def test_all_problems_with_line_numbers() -> None:
    data = (
        b"team_number,team_name\n"
        b"1,Alpha\n"
        b"two,Beta\n"
        b"1,Alpha again\n"
        b"4.0,Delta\n"
        b"5,\n"
        b",Nameless\n"
        b"-3,Negative\n"
    )
    report = parse_teams_csv(data)
    assert not report.ok
    assert report.errors == [
        "Line 3: team_number must be a whole number (got 'two')",
        "Line 4: team_number 1 is already used on line 2",
        "Line 5: team_number must be a whole number (got '4.0')",
        "Line 6: team_name is blank",
        "Line 7: team_number must be a whole number (got blank)",
        "Line 8: team_number is -3 but must be at least 0",
    ]
    assert len(report.teams) == 1


def test_missing_header() -> None:
    report = parse_teams_csv(b"1,Alpha\n2,Beta\n")
    assert report.errors == [
        "Line 1: header must contain team_number,team_name (missing team_number, team_name)"
    ]


def test_extra_column_warns() -> None:
    report = parse_teams_csv(b"team_number,team_name,coach\n1,Alpha,Smith\n")
    assert report.ok
    assert report.warnings == ["Line 1: extra column(s) ignored: coach"]


def test_not_utf8() -> None:
    report = parse_teams_csv("team_number,team_name\n1,Café\n".encode("utf-16"))
    assert report.errors[0].startswith("File is not UTF-8 text")


def test_header_only() -> None:
    assert parse_teams_csv(b"team_number,team_name\n").errors == ["No teams found below the header"]


def test_import_from_file(tmp_path: Path) -> None:
    path = tmp_path / "teams.csv"
    path.write_bytes(b"\xef\xbb\xbfteam_number,team_name\n1,Alpha\n")
    report = import_teams_csv(path)
    assert report.ok and report.source == "teams.csv"
    assert "Result: OK - 1 teams" in report.to_text()


def test_missing_file(tmp_path: Path) -> None:
    report = import_teams_csv(tmp_path / "nope.csv")
    assert report.errors[0].startswith("Could not read nope.csv")


# --- saving (SQLite + Postgres) --------------------------------------------


def _teams(*pairs: tuple[int, str]) -> list[TeamRow]:
    return [TeamRow(team_number=n, team_name=name) for n, name in pairs]


def test_save_inserts_then_upserts(db: Session) -> None:
    first = save_teams(db, _teams((1, "Alpha"), (2, "Beta")))
    assert (first.inserted, first.updated) == (2, 0)
    second = save_teams(db, _teams((2, "Beta Renamed"), (3, "Gamma"), (1, "Alpha")))
    assert (second.inserted, second.updated) == (1, 1)
    db.expire_all()
    rows = {t.team_number: t.name for t in db.scalars(select(Team))}
    assert rows == {1: "Alpha", 2: "Beta Renamed", 3: "Gamma"}


@pytest.mark.parametrize(("number", "warned"), [(99, False), (100, True)])
def test_save_warns_when_number_exceeds_grid(db: Session, number: int, warned: bool) -> None:
    db.add(
        Event(code="AP", name="A&P", tournament="T", sheet_version=1, team_number_digits=2,
              total_points=Decimal("200"), free_response_max=Decimal("140"))
    )  # fmt: skip
    db.flush()
    result = save_teams(db, _teams((number, "Team")))
    assert bool(result.warnings) is warned
    if warned:
        assert "team 100 needs more than 2 digits" in result.warnings[0]
