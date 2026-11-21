"""Save a validated ``EventSetup`` to the database, and load it back.

Re-import rules (see docs/DECISIONS.md):
- new ``event_id``                      -> insert event + questions
- existing, no scans yet                -> update event, replace questions
- existing, has scans, higher version   -> update event, replace questions; old scans keep
                                           their own ``sheet_version`` (re-scoring is phase 5)
- existing, has scans, same/lower ver.  -> refused with ``EventLockedError``

Nothing is committed here: the caller commits, so the whole save is one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Event, Question, Scan
from app.schemas.event_setup import EventSetup, QuestionSetup


class SaveAction(StrEnum):
    created = "created"
    replaced = "replaced"  # no scans yet, questions swapped
    new_version = "new_version"  # had scans, sheet_version went up


class EventLockedError(ValueError):
    """Re-import would change the key under existing scores without a version bump."""


@dataclass(frozen=True)
class SaveResult:
    action: SaveAction
    event_id: int
    code: str
    question_count: int
    scan_count: int

    def to_text(self) -> str:
        what = {
            SaveAction.created: "Saved new event",
            SaveAction.replaced: "Replaced questions for existing event (no scans yet)",
            SaveAction.new_version: (
                f"Saved new sheet version; {self.scan_count} existing scan(s) keep their "
                "old version and are not re-scored yet"
            ),
        }[self.action]
        return f"{what}: {self.code} ({self.question_count} questions)"


def _question_row(q: QuestionSetup) -> Question:
    return Question(
        q=q.q,
        points=q.points,
        options=q.options,
        correct=q.correct_csv,
        scoring=q.scoring,
        penalty_per_wrong=q.penalty_per_wrong,
    )


def save_event(session: Session, setup: EventSetup, source_filename: str | None) -> SaveResult:
    info = setup.event
    event = session.scalars(select(Event).where(Event.code == info.event_id)).one_or_none()
    scan_count = 0

    if event is None:
        action = SaveAction.created
        event = Event(code=info.event_id)
        session.add(event)
    else:
        scan_count = (
            session.scalar(select(func.count()).select_from(Scan).where(Scan.event_id == event.id))
            or 0
        )
        if scan_count == 0:
            action = SaveAction.replaced
        elif info.sheet_version > event.sheet_version:
            action = SaveAction.new_version
        else:
            raise EventLockedError(
                f"Event {info.event_id} already has {scan_count} scan(s) scored with sheet "
                f"version {event.sheet_version}. To change the key, raise sheet_version "
                f"above {event.sheet_version} on the Event tab and import again."
            )
        # Delete old questions first so the (event_id, q) unique rule is never hit mid-swap.
        event.questions.clear()
        session.flush()

    event.name = info.event_name
    event.tournament = info.tournament
    event.event_date = info.date
    event.sheet_version = info.sheet_version
    event.team_number_digits = info.team_number_digits
    event.total_points = info.total_points
    event.free_response_max = info.free_response_max
    event.source_filename = source_filename
    event.questions.extend(_question_row(q) for q in setup.questions)
    session.flush()

    return SaveResult(
        action=action,
        event_id=event.id,
        code=event.code,
        question_count=len(setup.questions),
        scan_count=scan_count,
    )


def question_setup_from_row(row: Question) -> QuestionSetup:
    return QuestionSetup(
        q=row.q,
        points=row.points,
        options=row.options,
        correct=row.correct,
        scoring=row.scoring,
        penalty_per_wrong=row.penalty_per_wrong,
    )


def load_questions(session: Session, code: str) -> list[QuestionSetup]:
    """Questions of a saved event, as scoring-ready ``QuestionSetup`` objects."""
    event = session.scalars(select(Event).where(Event.code == code)).one_or_none()
    if event is None:
        raise LookupError(f"No event with event_id {code!r} in the database")
    return [question_setup_from_row(q) for q in event.questions]
