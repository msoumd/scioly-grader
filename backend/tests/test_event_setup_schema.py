from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.event_setup import EventInfo, EventSetup, QuestionSetup


def _event(**kw: object) -> EventInfo:
    base = dict(
        event_id="AP",
        event_name="A&P",
        tournament="T",
        team_number_digits=2,
        total_points=Decimal("200"),
        free_response_max=Decimal("140"),
    )
    return EventInfo(**(base | kw))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("D", ("D",)),
        ("a, c", ("A", "C")),
        ("C,A", ("A", "C")),
        ("AC", ("A", "C")),
        (["b", "a"], ("A", "B")),
    ],
)
def test_correct_letters_normalised(raw: object, expected: tuple[str, ...]) -> None:
    assert QuestionSetup(q=1, points=1, options=5, correct=raw).correct == expected


def test_correct_letter_beyond_options_rejected() -> None:
    with pytest.raises(ValidationError, match=r"F is beyond the 5 options \(A-E\)"):
        QuestionSetup(q=7, points=1, options=5, correct="F")


@pytest.mark.parametrize("options", [1, 10])
def test_options_range(options: int) -> None:
    with pytest.raises(ValidationError):
        QuestionSetup(q=1, points=1, options=options, correct="A")


def test_penalty_requires_partial() -> None:
    with pytest.raises(ValidationError, match="only applies to 'partial'"):
        QuestionSetup(q=1, points=1, options=4, correct="A", penalty_per_wrong=Decimal("0.5"))
    QuestionSetup(
        q=1, points=2, options=4, correct="A,B", scoring="partial", penalty_per_wrong=Decimal("0.5")
    )


def test_totals_must_add_up() -> None:
    qs = [QuestionSetup(q=i, points=1, options=5, correct="A") for i in range(1, 61)]
    assert EventSetup(event=_event(), questions=qs).mcq_points_total == 60
    with pytest.raises(ValidationError, match=r"total_points is 210"):
        EventSetup(event=_event(total_points=Decimal("210")), questions=qs)


def test_duplicate_question_numbers_rejected() -> None:
    qs = [QuestionSetup(q=1, points=1, options=5, correct="A")] * 2
    with pytest.raises(ValidationError, match="duplicate question numbers"):
        EventSetup(event=_event(total_points=Decimal("142")), questions=qs)
