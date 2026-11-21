"""Schema-level guarantees enforced by the database itself."""

from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Event, FreeResponseScore, Grader, Question, Scan, ScoringMode

EXPECTED_TABLES = {
    "graders",
    "events",
    "questions",
    "teams",
    "scans",
    "free_response_scores",
    "audit_log",
}


def _seed(db: Session) -> tuple[Event, Grader]:
    grader = Grader(name="Alice")
    event = Event(
        code="AP",
        name="Anatomy and Physiology",
        tournament="Test Invitational",
        sheet_version=1,
        team_number_digits=2,
        total_points=Decimal("200"),
        free_response_max=Decimal("140"),
    )
    db.add_all([grader, event])
    db.flush()
    return event, grader


def test_all_tables_exist(db: Session) -> None:
    assert set(inspect(db.get_bind()).get_table_names()) >= EXPECTED_TABLES


def test_question_roundtrip(db: Session) -> None:
    event, _ = _seed(db)
    db.add(
        Question(
            event_id=event.id,
            q=1,
            points=Decimal("2"),
            options=5,
            correct="A,C",
            scoring=ScoringMode.partial,
            penalty_per_wrong=Decimal("0.5"),
        )
    )
    db.flush()
    db.expire_all()
    q = db.get(Event, event.id).questions[0]  # type: ignore[union-attr]
    assert (q.correct, q.scoring, q.penalty_per_wrong) == (
        "A,C",
        ScoringMode.partial,
        Decimal("0.5"),
    )


def test_duplicate_question_number_rejected(db: Session) -> None:
    event, _ = _seed(db)
    db.add_all(
        [
            Question(event_id=event.id, q=1, points=1, options=5, correct="A"),
            Question(event_id=event.id, q=1, points=1, options=5, correct="B"),
        ]
    )
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("options", [1, 10])
def test_options_out_of_range_rejected(db: Session, options: int) -> None:
    event, _ = _seed(db)
    db.add(Question(event_id=event.id, q=1, points=1, options=options, correct="A"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_only_one_counted_scan_per_team(db: Session) -> None:
    event, grader = _seed(db)

    def scan(counted: bool) -> Scan:
        return Scan(
            event_id=event.id,
            team_number=12,
            sheet_version=1,
            image_path="x.jpg",
            grader_id=grader.id,
            is_counted=counted,
        )

    # Duplicates are fine while at most one counts.
    db.add_all([scan(True), scan(False), scan(False)])
    db.flush()
    db.add(scan(True))
    with pytest.raises(IntegrityError):
        db.flush()


def test_one_free_response_per_team(db: Session) -> None:
    event, grader = _seed(db)
    db.add_all(
        [
            FreeResponseScore(
                event_id=event.id, team_number=5, value=Decimal("10"), grader_id=grader.id
            ),
            FreeResponseScore(
                event_id=event.id, team_number=5, value=Decimal("11"), grader_id=grader.id
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("value", ["-1", "10.25"])
def test_free_response_value_rules(db: Session, value: str) -> None:
    event, grader = _seed(db)
    db.add(
        FreeResponseScore(
            event_id=event.id, team_number=5, value=Decimal(value), grader_id=grader.id
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_event_cascades_questions(db: Session) -> None:
    event, _ = _seed(db)
    db.add(Question(event_id=event.id, q=1, points=1, options=5, correct="A"))
    db.flush()
    db.execute(text("DELETE FROM events WHERE id = :id"), {"id": event.id})
    assert db.execute(text("SELECT count(*) FROM questions")).scalar_one() == 0


def test_rls_enabled_on_postgres(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("RLS is Postgres/Supabase only")
    rows = db.execute(
        text("SELECT relname FROM pg_class WHERE relrowsecurity AND relname = ANY(:t)"),
        {"t": list(EXPECTED_TABLES)},
    ).scalars()
    assert set(rows) == EXPECTED_TABLES
