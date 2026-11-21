"""Scoring rules. A bug here silently changes a team's rank, so cases are spelled out."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.db.models import ScoringMode
from app.schemas.event_setup import LETTERS, QuestionSetup
from app.services.scoring import fmt_points, round_points, score_question, score_sheet

D = Decimal


def q(
    correct: str,
    points: str = "1",
    options: int = 5,
    scoring: str = "exact",
    penalty: str = "0",
    num: int = 1,
) -> QuestionSetup:
    return QuestionSetup(
        q=num,
        points=D(points),
        options=options,
        correct=correct,
        scoring=ScoringMode(scoring),
        penalty_per_wrong=D(penalty),
    )


# (case id, question, marked letters, expected points)
CASES: list[tuple[str, QuestionSetup, set[str], str]] = [
    # --- exact, single answer
    ("single correct", q("D"), {"D"}, "1"),
    ("single wrong", q("D"), {"A"}, "0"),
    ("single blank", q("D"), set(), "0"),
    ("single correct + extra", q("D"), {"D", "A"}, "0"),
    ("single all marked", q("D"), set("ABCDE"), "0"),
    ("single lowercase mark", q("D"), {"d"}, "1"),
    ("single 2 points correct", q("B", points="2"), {"B"}, "2"),
    ("single half point correct", q("B", points="0.5"), {"B"}, "0.5"),
    ("single 9 options last letter", q("I", options=9), {"I"}, "1"),
    ("single 2 options", q("B", options=2), {"B"}, "1"),
    # --- exact, multi-select
    ("multi exact match", q("C,D"), {"C", "D"}, "1"),
    ("multi missing one", q("C,D"), {"C"}, "0"),
    ("multi with extra", q("C,D"), {"C", "D", "E"}, "0"),
    ("multi all marked", q("A,B,D", points="2"), set("ABCDE"), "0"),
    ("multi blank", q("A,B,D", points="2"), set(), "0"),
    ("multi 3 of 3", q("B,D,E", points="2"), {"B", "D", "E"}, "2"),
    ("multi wrong set same size", q("A,E"), {"A", "D"}, "0"),
    # --- partial, no penalty
    ("partial full", q("A,B", points="2", scoring="partial"), {"A", "B"}, "2"),
    ("partial half", q("A,B", points="2", scoring="partial"), {"A"}, "1"),
    ("partial blank", q("A,B", points="2", scoring="partial"), set(), "0"),
    ("partial one of three", q("A,B,D", points="3", scoring="partial"), {"D"}, "1"),
    ("partial two of three", q("A,B,D", points="3", scoring="partial"), {"A", "D"}, "2"),
    # over-marking with no penalty: extra picks cost nothing (documented rule)
    ("partial extra no penalty", q("A,B", points="2", scoring="partial"), {"A", "C"}, "1"),
    ("partial all marked no penalty", q("A,B", points="2", scoring="partial"), set("ABCDE"), "2"),
    ("partial single-answer key", q("C", points="1", scoring="partial"), {"C"}, "1"),
    # --- partial with penalty
    (
        "partial penalty one wrong",
        q("A,B", points="2", scoring="partial", penalty="0.25"),
        {"A", "C"},
        "0.75",
    ),
    (
        "partial penalty full + wrong",
        q("A,B", points="2", scoring="partial", penalty="0.5"),
        {"A", "B", "C"},
        "1.5",
    ),
    (
        "partial penalty floored at 0",
        q("A,B", points="2", scoring="partial", penalty="1"),
        {"C", "D", "E"},
        "0",
    ),
    (
        "partial penalty all marked",
        q("A,B", points="2", scoring="partial", penalty="0.25"),
        set("ABCDE"),
        "1.25",
    ),
    (
        "partial penalty only wrong",
        q("A,B", points="2", scoring="partial", penalty="0.25"),
        {"C"},
        "0",
    ),
    (
        "partial penalty half points",
        q("A,B", points="0.5", scoring="partial", penalty="0.1"),
        {"A", "E"},
        "0.15",
    ),
    # letters beyond the options count as wrong picks
    (
        "partial out-of-range mark",
        q("A,B", points="2", scoring="partial", penalty="0.5"),
        {"A", "Z"},
        "0.5",
    ),
]


@pytest.mark.parametrize(
    ("question", "marked", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_score_question(question: QuestionSetup, marked: set[str], expected: str) -> None:
    assert score_question(marked, question) == D(expected)


def test_partial_never_above_points() -> None:
    # A correct + no penalty on the extra still cannot exceed the question's points
    assert score_question(set("ABCDE"), q("A,B,C,D,E", points="2", scoring="partial")) == D("2")


def test_partial_thirds_kept_exact_per_question() -> None:
    one_third = score_question({"A"}, q("A,B,C", points="1", scoring="partial"))
    assert round_points(one_third) == D("0.33")
    assert one_third * 3 == pytest.approx(D("1"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.125", "0.13"), ("0.135", "0.14"), ("0.124999", "0.12"), ("1.005", "1.01"), ("2", "2.00")],
)
def test_round_points_half_up(value: str, expected: str) -> None:
    assert round_points(D(value)) == D(expected)


@pytest.mark.parametrize(
    ("value", "expected"), [("60", "60"), ("200.00", "200"), ("0.50", "0.5"), ("1.3333", "1.33")]
)
def test_fmt_points(value: str, expected: str) -> None:
    assert fmt_points(D(value)) == expected


def test_score_sheet_total_and_unanswered() -> None:
    questions = [
        q("D", num=1),
        q("C,D", num=2),
        q("B", points="2", num=3),
        q("A,B,C", points="1", scoring="partial", num=4),
    ]
    result = score_sheet({1: {"D"}, 2: {"C"}, 4: {"A"}}, questions)
    assert result.per_question[1] == D("1")
    assert result.per_question[2] == D("0")
    assert result.per_question[3] == D("0")  # unanswered
    assert result.total == D("1.33")  # 1 + 1/3, rounded once at the end
    assert result.max_total == D("5")


def test_score_sheet_rounds_total_not_each_question() -> None:
    # Three questions each worth 1/3 point: per-question rounding would give 0.99.
    questions = [q("A,B,C", scoring="partial", num=n) for n in (1, 2, 3)]
    result = score_sheet({1: {"A"}, 2: {"B"}, 3: {"C"}}, questions)
    assert result.total == D("1.00")


def test_score_sheet_rejects_unknown_question() -> None:
    with pytest.raises(ValueError, match=r"not in this event: \[9\]"):
        score_sheet({9: {"A"}}, [q("A", num=1)])


# --- property tests ---------------------------------------------------------


@st.composite
def question_and_marks(draw: st.DrawFn) -> tuple[QuestionSetup, set[str]]:
    options = draw(st.integers(2, 9))
    letters = LETTERS[:options]
    correct = draw(st.sets(st.sampled_from(letters), min_size=1))
    scoring = draw(st.sampled_from(list(ScoringMode)))
    points = draw(st.decimals(min_value=D("0.5"), max_value=D("10"), places=1))
    penalty = (
        draw(st.decimals(min_value=D("0"), max_value=D("2"), places=2))
        if scoring is ScoringMode.partial
        else D("0")
    )
    question = QuestionSetup(
        q=1,
        points=points,
        options=options,
        correct=sorted(correct),
        scoring=scoring,
        penalty_per_wrong=penalty,
    )
    marked = draw(st.sets(st.sampled_from(letters)))
    return question, marked


@given(question_and_marks())
def test_score_within_bounds(data: tuple[QuestionSetup, set[str]]) -> None:
    question, marked = data
    assert D("0") <= score_question(marked, question) <= question.points


@given(question_and_marks())
def test_exact_is_all_or_nothing(data: tuple[QuestionSetup, set[str]]) -> None:
    question, marked = data
    if question.scoring is ScoringMode.exact:
        assert score_question(marked, question) in {D("0"), question.points}


@given(question_and_marks())
def test_marking_exactly_the_key_gives_full_points(data: tuple[QuestionSetup, set[str]]) -> None:
    question, _ = data
    assert score_question(set(question.correct), question) == question.points


@given(question_and_marks())
def test_blank_scores_zero(data: tuple[QuestionSetup, set[str]]) -> None:
    question, _ = data
    assert score_question(set(), question) == D("0")
