"""Spreadsheet importer: the real A&P file, and small broken fixtures with exact messages."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.db.models import ScoringMode
from app.services.event_import import import_event_workbook

FIXTURES = Path(__file__).parent / "fixtures" / "event_setup"
AP_FILE = Path(__file__).resolve().parents[2] / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"


def test_ap_file_imports_cleanly() -> None:
    report = import_event_workbook(AP_FILE)
    assert report.errors == []
    assert report.ok
    assert report.question_count == 54
    assert report.mcq_points_total == Decimal("60")
    assert (report.single_count, report.multi_count) == (48, 6)
    assert report.scoring_counts == {"exact": 54, "partial": 0}
    assert report.tabs_ignored == ["Instructions", "Unassigned 55-66"]
    assert report.setup is not None
    ev = report.setup.event
    assert (ev.event_id, ev.total_points, ev.free_response_max) == ("AP", 200, 140)
    # The sheet's own note about the open 200-vs-210 question is surfaced, not lost.
    assert any("210" in note for note in report.notes)


@pytest.mark.parametrize(
    ("q", "correct", "points"),
    [(1, ("D",), "1"), (9, ("C", "D"), "1"), (11, ("D",), "2"), (25, ("B", "D", "E"), "2"),
     (35, ("A", "B", "D"), "2"), (54, ("B",), "1")],
)  # fmt: skip
def test_ap_spot_check_answers(q: int, correct: tuple[str, ...], points: str) -> None:
    report = import_event_workbook(AP_FILE)
    assert report.setup is not None
    question = next(x for x in report.setup.questions if x.q == q)
    assert (question.correct, question.points) == (correct, Decimal(points))


def test_ap_report_text() -> None:
    text = import_event_workbook(AP_FILE).to_text()
    assert "Result: OK" in text
    assert "Questions: 54 (48 single-answer, 6 multi-select)" in text
    assert "Total points: 200 (check passes: 140 + 60 = 200)" in text
    assert "Tabs not imported: Instructions, Unassigned 55-66" in text


def test_valid_fixture_defaults() -> None:
    report = import_event_workbook(FIXTURES / "valid.xlsx")
    assert report.ok, report.errors
    assert report.setup is not None
    by_q = {q.q: q for q in report.setup.questions}
    assert by_q[4].scoring is ScoringMode.exact  # blank scoring -> exact
    assert by_q[1].penalty_per_wrong == 0  # blank penalty -> 0
    assert by_q[5].penalty_per_wrong == Decimal("0.25")
    assert by_q[3].correct == ("C", "D")
    assert report.warnings == []


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("missing_questions_tab.xlsx", "Missing tab 'Questions'"),
        ("missing_event_tab.xlsx", "Missing tab 'Event'"),
        ("missing_column.xlsx", "Questions tab: header row is missing column: correct"),
        (
            "letter_beyond_options.xlsx",
            "Questions row 3 (q 2): correct answer F is beyond the 5 options (A-E)",
        ),
        ("options_10.xlsx", "Questions row 3 (q 2): options is 10 but must be at most 9"),
        ("duplicate_q.xlsx", "Questions row 5 (q 2): question number 2 is already used on row 3"),
        (
            "totals_mismatch.xlsx",
            "Event row 8: total_points is 11 but free_response_max (5) "
            "+ multiple-choice points (5) = 10",
        ),
        ("non_numeric_points.xlsx", "Questions row 4 (q 3): points must be a number (got 'two')"),
        ("blank_required_setting.xlsx", "Event row 4: required setting 'tournament' is blank"),
        (
            "bad_scoring_mode.xlsx",
            "Questions row 2 (q 1): scoring must be 'exact' or 'partial' (got 'half')",
        ),
        (
            "penalty_on_exact.xlsx",
            "Questions row 2 (q 1): penalty_per_wrong only applies to 'partial'",
        ),
    ],
)
def test_broken_fixture_message(filename: str, expected: str) -> None:
    report = import_event_workbook(FIXTURES / filename)
    assert not report.ok
    assert report.setup is None
    assert report.errors == [expected]


def test_all_problems_listed_at_once() -> None:
    report = import_event_workbook(FIXTURES / "many_problems.xlsx")
    assert report.errors == [
        "Questions row 2 (q 1): points must be a number (got 'one')",
        "Questions row 4 (q 3): correct answer G is beyond the 5 options (A-E)",
        "Questions row 5 (q 4): options is 12 but must be at most 9",
    ]
    assert "Result: FAILED - 3 problems to fix" in report.to_text()


def test_both_tabs_missing_reported_together(tmp_path: Path) -> None:
    from tests.fixtures.event_setup.build import build

    report = import_event_workbook(build(tmp_path / "empty.xlsx", tabs=()))
    assert report.errors == ["Missing tab 'Event'", "Missing tab 'Questions'"]


def test_event_and_question_errors_together(tmp_path: Path) -> None:
    from tests.fixtures.event_setup.build import EVENT, QUESTIONS, build

    event = [(k, None if k == "date" else v) for k, v in EVENT]
    questions = [list(r) for r in QUESTIONS]
    questions[1][3] = "Z"
    report = import_event_workbook(build(tmp_path / "x.xlsx", event=event, questions=questions))
    assert report.errors == [
        "Event row 5: required setting 'date' is blank",
        "Questions row 3 (q 2): correct answer Z is beyond the 5 options (A-E)",
    ]


def test_unknown_setting_and_column_are_warnings(tmp_path: Path) -> None:
    from tests.fixtures.event_setup.build import EVENT, HEADER, QUESTIONS, build

    report = import_event_workbook(
        build(
            tmp_path / "x.xlsx",
            event=[*EVENT, ("room", "B101")],
            header=[*HEADER, "difficulty"],
            questions=[[*r, "easy"] for r in QUESTIONS],
        )
    )
    assert report.ok, report.errors
    assert report.warnings == [
        "Event row 12: unknown setting 'room' was ignored",
        "Questions tab: unknown column 'difficulty' was ignored",
    ]


def test_blank_rows_skipped_and_letters_normalised(tmp_path: Path) -> None:
    from tests.fixtures.event_setup.build import QUESTIONS, build

    rows = [list(r) for r in QUESTIONS]
    rows[2][3] = " c d "  # "C D" with odd spacing/case
    rows.insert(2, [None] * 7)
    report = import_event_workbook(build(tmp_path / "x.xlsx", questions=rows))
    assert report.ok, report.errors
    assert report.setup is not None
    assert report.setup.questions[2].correct == ("C", "D")
    assert report.rows_read == 5


def test_missing_required_setting(tmp_path: Path) -> None:
    from tests.fixtures.event_setup.build import EVENT, build

    report = import_event_workbook(
        build(tmp_path / "x.xlsx", event=[r for r in EVENT if r[0] != "sheet_version"])
    )
    assert report.errors == ["Event tab: required setting 'sheet_version' is missing"]


def test_no_questions(tmp_path: Path) -> None:
    from tests.fixtures.event_setup.build import build

    report = import_event_workbook(build(tmp_path / "x.xlsx", questions=[]))
    assert report.errors == ["Questions tab: no questions found"]


def test_not_a_workbook(tmp_path: Path) -> None:
    bad = tmp_path / "notes.xlsx"
    bad.write_text("not a spreadsheet")
    report = import_event_workbook(bad)
    assert not report.ok
    assert report.errors[0].startswith("Could not open notes.xlsx as an .xlsx workbook")


# --- the app is event-agnostic: every example setup must import cleanly ---------

EXAMPLES_DIR = AP_FILE.parent
FORENSICS_FILE = EXAMPLES_DIR / "EXAMPLE_forensics_event_setup.xlsx"


@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.xlsx")), ids=lambda p: p.name)
def test_every_example_setup_imports_cleanly(path: Path) -> None:
    report = import_event_workbook(path)
    assert report.ok, report.errors
    assert report.warnings == []


def test_forensics_shaped_event() -> None:
    """Mostly free response; few bubble questions, numbered with gaps, 3-5 options."""
    report = import_event_workbook(FORENSICS_FILE)
    assert report.setup is not None
    qs = report.setup.questions
    assert [q.q for q in qs] == [25, 45, 49, 57, 58, 59, 60, 62, 63, 68, 69]
    assert {q.options for q in qs} == {3, 4, 5}
    assert report.mcq_points_total == Decimal("14")
    assert report.setup.event.free_response_max == Decimal("286")
    assert [q.points for q in qs if q.q in (68, 69)] == [Decimal("0.5"), Decimal("0.5")]
