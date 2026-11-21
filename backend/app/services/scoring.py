"""Turn marked bubbles into points.

- ``exact``: full points only if the marked set equals the key, else 0.
- ``partial``: ``points × (correct picks / number of correct answers)
  − penalty_per_wrong × wrong picks``, floored at 0 and capped at ``points``.

All arithmetic is ``Decimal``. Per-question values are kept exact; only the sheet
total is rounded (2 decimals, half-up) so it matches a hand calculation.
See docs/DECISIONS.md ("Scoring rules").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.db.models import ScoringMode
from app.schemas.event_setup import EventSetup, QuestionSetup

ZERO = Decimal("0")
CENT = Decimal("0.01")


def normalise_marks(marked: Iterable[str]) -> frozenset[str]:
    """Uppercase, strip and de-duplicate marked letters; ignore blanks."""
    return frozenset(m.strip().upper() for m in marked if m and m.strip())


def score_question(marked: Iterable[str], q: QuestionSetup) -> Decimal:
    """Points earned on one question for the given set of marked letters.

    Letters beyond the question's options (which detection should never produce)
    simply count as wrong picks.
    """
    picks = normalise_marks(marked)
    key = frozenset(q.correct)

    if q.scoring is ScoringMode.exact:
        return q.points if picks == key else ZERO

    hits = len(picks & key)
    wrong = len(picks - key)
    raw = q.points * hits / len(key) - q.penalty_per_wrong * wrong
    return min(max(raw, ZERO), q.points)


def round_points(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SheetScore:
    per_question: dict[int, Decimal] = field(default_factory=dict)
    total: Decimal = ZERO  # rounded to 2 decimals, half-up
    max_total: Decimal = ZERO


def score_sheet(
    marks: Mapping[int, Iterable[str]],
    setup: EventSetup | Sequence[QuestionSetup],
) -> SheetScore:
    """Score every question in ``setup``. A question missing from ``marks`` is unanswered.

    Raises ``ValueError`` if ``marks`` mentions a question number the event does not have,
    since that means the marks and the key are out of step.
    """
    questions = setup.questions if isinstance(setup, EventSetup) else list(setup)
    known = {q.q for q in questions}
    unknown = sorted(set(marks) - known)
    if unknown:
        raise ValueError(f"marks given for question(s) not in this event: {unknown}")

    per_question = {q.q: score_question(marks.get(q.q, ()), q) for q in questions}
    return SheetScore(
        per_question=per_question,
        total=round_points(sum(per_question.values(), ZERO)),
        max_total=sum((q.points for q in questions), ZERO),
    )
