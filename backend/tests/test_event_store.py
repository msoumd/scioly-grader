"""Saving imported events, including the re-import rules. Runs on SQLite and Postgres."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Event, Grader, Question, Scan, ScoringMode
from app.schemas.event_setup import EventSetup
from app.services.event_import import import_event_workbook
from app.services.event_store import (
    EventLockedError,
    SaveAction,
    load_questions,
    save_event,
)
from app.services.scoring import score_sheet

AP_FILE = Path(__file__).resolve().parents[2] / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"


def _setup(version: int = 1, correct_q1: str = "A", points_q2: str = "1") -> EventSetup:
    total = Decimal("5") + Decimal("1") + Decimal(points_q2)
    return EventSetup.model_validate(
        {
            "event": {
                "event_id": "TEST",
                "event_name": "Test Event",
                "tournament": "T",
                "sheet_version": version,
                "team_number_digits": 2,
                "total_points": total,
                "free_response_max": 5,
            },
            "questions": [
                {"q": 1, "points": 1, "options": 5, "correct": correct_q1},
                {
                    "q": 2,
                    "points": points_q2,
                    "options": 5,
                    "correct": "A,C",
                    "scoring": "partial",
                    "penalty_per_wrong": "0.25",
                },
            ],
        }
    )


def _add_scan(db: Session, event_id: int) -> None:
    grader = Grader(name="Alice")
    db.add(grader)
    db.flush()
    db.add(
        Scan(event_id=event_id, team_number=1, sheet_version=1, image_path="x.jpg",
             grader_id=grader.id)
    )  # fmt: skip
    db.flush()


def _question_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Question)) or 0


def test_insert_new_event(db: Session) -> None:
    result = save_event(db, _setup(), "test.xlsx")
    assert result.action is SaveAction.created
    db.expire_all()
    event = db.get(Event, result.event_id)
    assert event is not None
    assert (event.code, event.source_filename, len(event.questions)) == ("TEST", "test.xlsx", 2)
    q2 = event.questions[1]
    assert (q2.correct, q2.scoring, q2.penalty_per_wrong) == (
        "A,C",
        ScoringMode.partial,
        Decimal("0.25"),
    )


def test_reimport_before_scans_replaces_questions(db: Session) -> None:
    first = save_event(db, _setup(correct_q1="A"), "v1.xlsx")
    second = save_event(db, _setup(correct_q1="B", points_q2="2"), "v1-fixed.xlsx")
    assert second.action is SaveAction.replaced
    assert second.event_id == first.event_id
    db.expire_all()
    event = db.get(Event, first.event_id)
    assert event is not None
    assert [q.correct for q in event.questions] == ["B", "A,C"]
    assert event.total_points == Decimal("8")
    assert event.source_filename == "v1-fixed.xlsx"
    assert _question_count(db) == 2  # old rows gone, not duplicated


def test_reimport_with_scans_same_version_refused(db: Session) -> None:
    first = save_event(db, _setup(), "v1.xlsx")
    _add_scan(db, first.event_id)
    with pytest.raises(EventLockedError, match="raise sheet_version above 1"):
        save_event(db, _setup(correct_q1="B"), "v1-changed.xlsx")
    db.expire_all()
    event = db.get(Event, first.event_id)
    assert event is not None
    assert event.questions[0].correct == "A"  # key unchanged


def test_reimport_with_scans_higher_version_allowed(db: Session) -> None:
    first = save_event(db, _setup(), "v1.xlsx")
    _add_scan(db, first.event_id)
    result = save_event(db, _setup(version=2, correct_q1="B"), "v2.xlsx")
    assert result.action is SaveAction.new_version
    assert result.scan_count == 1
    db.expire_all()
    event = db.get(Event, first.event_id)
    assert event is not None
    assert (event.sheet_version, event.questions[0].correct) == (2, "B")
    scan = db.scalars(select(Scan)).one()
    assert scan.sheet_version == 1  # old scan keeps its version


def test_ap_roundtrip_and_score(db: Session) -> None:
    report = import_event_workbook(AP_FILE)
    assert report.setup is not None
    save_event(db, report.setup, AP_FILE.name)
    db.expire_all()
    questions = load_questions(db, "AP")
    assert questions == report.setup.questions
    perfect = {q.q: set(q.correct) for q in questions}
    assert score_sheet(perfect, questions).total == Decimal("60.00")


def test_load_unknown_event(db: Session) -> None:
    with pytest.raises(LookupError, match="No event with event_id 'NOPE'"):
        load_questions(db, "NOPE")
