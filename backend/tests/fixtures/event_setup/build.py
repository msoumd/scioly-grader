"""Regenerate the small event-setup fixture workbooks used by tests/test_event_import.py.

    uv run python tests/fixtures/event_setup/build.py

Each file is a minimal valid setup with one thing broken, so a test can check that the
importer names that exact problem with the right row number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent

EVENT: list[tuple[str, Any]] = [
    ("event_id", "TEST"),
    ("event_name", "Test Event"),
    ("tournament", "Fixture Invitational"),
    ("date", "2026-02-07"),
    ("sheet_version", 1),
    ("team_number_digits", 2),
    ("total_points", 10),
    ("free_response_max", 5),
    ("mcq_points_total (auto)", "=SUM(Questions!B2:B500)"),
    ("check (should be 0)", "=B8-B9-B10"),
]
HEADER = ["q", "points", "options", "correct", "scoring", "penalty_per_wrong", "notes"]
QUESTIONS: list[list[Any]] = [
    [1, 1, 5, "A", "exact", None, None],
    [2, 1, 5, "B", "exact", None, None],
    [3, 1, 5, "C,D", "exact", None, "multi-select"],
    [4, 1, 4, "D", None, None, "blank scoring means exact"],
    [5, 1, 5, "A,C", "partial", 0.25, None],
]


def build(
    path: Path,
    *,
    event: list[tuple[str, Any]] | None = None,
    header: list[str] | None = None,
    questions: list[list[Any]] | None = None,
    tabs: tuple[str, ...] = ("Event", "Questions"),
) -> Path:
    wb = Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]
    ws_info = wb.create_sheet("Instructions")
    ws_info.append(["Fixture workbook for importer tests"])
    if "Event" in tabs:
        ws = wb.create_sheet("Event")
        ws.append(["setting", "value"])
        for row in EVENT if event is None else event:
            ws.append(list(row))
    if "Questions" in tabs:
        ws = wb.create_sheet("Questions")
        ws.append(HEADER if header is None else header)
        for row in QUESTIONS if questions is None else questions:
            ws.append(row)
    wb.save(path)
    return path


def _replace_event(key: str, value: Any) -> list[tuple[str, Any]]:
    return [(k, value if k == key else v) for k, v in EVENT]


def _replace_q(index: int, col: str, value: Any) -> list[list[Any]]:
    rows = [list(r) for r in QUESTIONS]
    rows[index][HEADER.index(col)] = value
    return rows


def _drop_col(col: str) -> tuple[list[str], list[list[Any]]]:
    i = HEADER.index(col)
    return HEADER[:i] + HEADER[i + 1 :], [r[:i] + r[i + 1 :] for r in QUESTIONS]


def fixtures() -> dict[str, dict[str, Any]]:
    no_correct_header, no_correct_rows = _drop_col("correct")
    many = [list(r) for r in QUESTIONS]
    many[0][HEADER.index("points")] = "one"  # row 2
    many[2][HEADER.index("correct")] = "C,G"  # row 4
    many[3][HEADER.index("options")] = 12  # row 5
    return {
        "valid.xlsx": {},
        "missing_questions_tab.xlsx": {"tabs": ("Event",)},
        "missing_event_tab.xlsx": {"tabs": ("Questions",)},
        "missing_column.xlsx": {"header": no_correct_header, "questions": no_correct_rows},
        "letter_beyond_options.xlsx": {"questions": _replace_q(1, "correct", "F")},
        "options_10.xlsx": {"questions": _replace_q(1, "options", 10)},
        "duplicate_q.xlsx": {"questions": _replace_q(3, "q", 2)},
        "totals_mismatch.xlsx": {"event": _replace_event("total_points", 11)},
        "non_numeric_points.xlsx": {"questions": _replace_q(2, "points", "two")},
        "blank_required_setting.xlsx": {"event": _replace_event("tournament", None)},
        "bad_scoring_mode.xlsx": {"questions": _replace_q(0, "scoring", "half")},
        "penalty_on_exact.xlsx": {"questions": _replace_q(0, "penalty_per_wrong", 0.5)},
        "many_problems.xlsx": {"questions": many},
    }


def main() -> None:
    for name, kwargs in fixtures().items():
        build(HERE / name, **kwargs)
        print("wrote", name)


if __name__ == "__main__":
    main()
