"""Read a supervisor's event-setup ``.xlsx`` into a validated ``EventSetup`` plus a report.

Every problem is collected in one pass and phrased with the tab and spreadsheet row,
e.g. ``Questions row 12 (q 11): correct answer F is beyond the 5 options (A-E)``.
Formula cells are never relied on: totals are recomputed from the question rows.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.db.models import ScoringMode
from app.schemas.event_setup import EventInfo, EventSetup, QuestionSetup

EVENT_TAB = "Event"
QUESTIONS_TAB = "Questions"

REQUIRED_SETTINGS = (
    "event_id",
    "event_name",
    "tournament",
    "date",
    "sheet_version",
    "team_number_digits",
    "total_points",
    "free_response_max",
)
OPTIONAL_SETTINGS = ("notes",)
REQUIRED_COLUMNS = ("q", "points", "options", "correct", "scoring")
OPTIONAL_COLUMNS = ("penalty_per_wrong", "notes")


# --- report -----------------------------------------------------------------


@dataclass
class ImportReport:
    source: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # free text from the sheet's notes rows
    tabs_ignored: list[str] = field(default_factory=list)
    rows_read: int = 0
    setup: EventSetup | None = None

    @property
    def ok(self) -> bool:
        return not self.errors and self.setup is not None

    @property
    def question_count(self) -> int:
        return len(self.setup.questions) if self.setup else 0

    @property
    def mcq_points_total(self) -> Decimal:
        return self.setup.mcq_points_total if self.setup else Decimal("0")

    @property
    def scoring_counts(self) -> dict[str, int]:
        counts = Counter(q.scoring.value for q in self.setup.questions) if self.setup else Counter()
        return {mode.value: counts.get(mode.value, 0) for mode in ScoringMode}

    @property
    def single_count(self) -> int:
        return sum(len(q.correct) == 1 for q in self.setup.questions) if self.setup else 0

    @property
    def multi_count(self) -> int:
        return self.question_count - self.single_count

    def to_text(self) -> str:
        lines = [f"Event import: {self.source}"]
        if self.ok:
            lines.append("Result: OK")
        else:
            n = len(self.errors)
            lines.append(f"Result: FAILED - {n} problem{'s' if n != 1 else ''} to fix")
        if self.setup:
            ev = self.setup.event
            date = ev.date.isoformat() if ev.date else "no date"
            lines += [
                f"Event: {ev.event_id} - {ev.event_name} ({ev.tournament}), {date}, "
                f"sheet version {ev.sheet_version}, {ev.team_number_digits}-digit team numbers",
                f"Questions: {self.question_count} "
                f"({self.single_count} single-answer, {self.multi_count} multi-select)",
                "Scoring: " + ", ".join(f"{k} {v}" for k, v in self.scoring_counts.items()),
                f"Multiple-choice points: {_fmt(self.mcq_points_total)}",
                f"Free-response max: {_fmt(ev.free_response_max)}",
                f"Total points: {_fmt(ev.total_points)} (check passes: "
                f"{_fmt(ev.free_response_max)} + {_fmt(self.mcq_points_total)} "
                f"= {_fmt(ev.total_points)})",
            ]
        elif self.rows_read:
            lines.append(f"Question rows read: {self.rows_read}")
        if self.tabs_ignored:
            lines.append("Tabs not imported: " + ", ".join(self.tabs_ignored))
        for title, items in (
            ("Notes from the sheet", self.notes),
            ("Warnings", self.warnings),
            ("Problems", self.errors),
        ):
            if items:
                lines.append(f"{title}:")
                lines += [f"  - {item}" for item in items]
        return "\n".join(lines)


def _fmt(value: Decimal) -> str:
    """200 -> '200', 0.50 -> '0.5'."""
    return format(value.normalize(), "f")


# --- cell helpers -----------------------------------------------------------


def _clean(value: Any) -> Any:
    """Strip strings; treat empty strings as blank (None)."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _as_text(value: Any) -> Any:
    """Text fields typed as numbers in Excel (e.g. event_id 12) become '12'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int | float):
        return str(value)
    return value


def _as_date(value: Any) -> Any:
    return value.date() if isinstance(value, dt.datetime) else value


def _row_label(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_COMPARE = {
    "greater_than": "more than",
    "greater_than_equal": "at least",
    "less_than": "less than",
    "less_than_equal": "at most",
}
_NUMBER_ERRORS = {
    "decimal_parsing",
    "decimal_type",
    "int_parsing",
    "int_type",
    "float_parsing",
    "float_type",
}


def describe_error(err: ErrorDetails) -> str:
    """Turn one Pydantic error into a sentence a supervisor can act on."""
    loc = err.get("loc") or ()
    name = str(loc[0]) if loc else ""
    kind = err["type"]
    got = err.get("input")
    ctx = err.get("ctx") or {}

    if kind in ("missing", "string_too_short") or (kind == "too_short" and name == "correct"):
        return f"{name} is blank"
    if kind in _NUMBER_ERRORS:
        return f"{name} must be a number (got {got!r})"
    if kind == "int_from_float":
        return f"{name} must be a whole number (got {got})"
    if kind in _COMPARE:
        limit = next(iter(ctx.values()), "?")
        return f"{name} is {_row_label(got)} but must be {_COMPARE[kind]} {limit}"
    if kind == "decimal_max_places":
        return f"{name} {got} has more than {ctx.get('decimal_places', 2)} decimal places"
    if kind == "decimal_max_digits":
        return f"{name} {got} is too large"
    if kind == "enum":
        return f"{name} must be 'exact' or 'partial' (got {got!r})"
    if kind.startswith("date") or kind.startswith("datetime"):
        return f"{name} must be a date like 2026-02-07 (got {got!r})"
    if kind == "string_pattern_mismatch":
        return f"{name} may only use letters, digits, '-' and '_' (got {got!r})"
    if kind == "string_too_long":
        return f"{name} is too long (max {ctx.get('max_length')} characters)"
    if kind == "value_error":
        msg = str(ctx.get("error", err["msg"]))
        # Schema messages start with "question N: "; the caller already labels the row.
        return msg.split(": ", 1)[1] if msg.startswith("question ") and ": " in msg else msg
    return f"{name}: {err['msg']}" if name else err["msg"]


# --- tabs -------------------------------------------------------------------


def _is_formula_row(key: str) -> bool:
    return "(auto)" in key or key.startswith("check")


def _read_event_tab(ws: Worksheet, report: ImportReport, rows: dict[str, int]) -> EventInfo | None:
    """Fill ``rows`` with setting -> spreadsheet row number, for later messages."""
    values: dict[str, Any] = {}
    for row_no, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if not row or all(_clean(c) is None for c in row):
            continue
        key = _clean(row[0])
        value = _clean(row[1]) if len(row) > 1 else None
        if key is None:
            continue
        key = str(key).strip().lower()
        if row_no == 1 and key == "setting":
            continue  # header row
        if _is_formula_row(key):
            continue
        if key in rows:
            report.errors.append(
                f"Event row {row_no}: setting '{key}' is repeated (first on row {rows[key]})"
            )
            continue
        rows[key] = row_no
        if key == "notes":
            if value is not None:
                report.notes.append(str(value))
            continue
        if key not in REQUIRED_SETTINGS:
            report.warnings.append(f"Event row {row_no}: unknown setting '{key}' was ignored")
            continue
        values[key] = value

    before = len(report.errors)
    for key in REQUIRED_SETTINGS:
        if key not in rows:
            report.errors.append(f"Event tab: required setting '{key}' is missing")
        elif values.get(key) is None:
            report.errors.append(f"Event row {rows[key]}: required setting '{key}' is blank")
    if len(report.errors) > before:
        return None

    data = {k: v for k, v in values.items() if v is not None}
    for k in ("event_id", "event_name", "tournament"):
        data[k] = _as_text(data[k])
    data["date"] = _as_date(data["date"])
    try:
        return EventInfo.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            key = str(err["loc"][0]) if err["loc"] else ""
            where = f"Event row {rows[key]}" if key in rows else "Event tab"
            report.errors.append(f"{where}: {describe_error(err)}")
        return None


def _read_questions_tab(ws: Worksheet, report: ImportReport) -> list[QuestionSetup] | None:
    rows = ws.iter_rows(values_only=True)
    header_row = next(rows, None)
    header = [str(_clean(c)).lower() if _clean(c) is not None else "" for c in header_row or ()]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        report.errors.append(
            "Questions tab: header row is missing column"
            f"{'s' if len(missing) > 1 else ''}: {', '.join(missing)}"
        )
        return None
    for name in header:
        if name and name not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
            report.warnings.append(f"Questions tab: unknown column '{name}' was ignored")
    col = {name: i for i, name in enumerate(header) if name}

    questions: list[QuestionSetup] = []
    seen: dict[int, int] = {}
    had_errors = False
    for row_no, row in enumerate(rows, start=2):
        cells = [_clean(c) for c in row]
        if all(c is None for c in cells):
            continue
        report.rows_read += 1

        def cell(name: str, cells: list[Any] = cells) -> Any:
            i = col.get(name)
            return cells[i] if i is not None and i < len(cells) else None

        q_val = cell("q")
        where = f"Questions row {row_no}" + (
            f" (q {_row_label(q_val)})" if q_val is not None else ""
        )
        data: dict[str, Any] = {
            "q": q_val,
            "points": cell("points"),
            "options": cell("options"),
            "correct": _as_text(cell("correct")),
            "scoring": str(cell("scoring")).lower() if cell("scoring") is not None else None,
            "penalty_per_wrong": cell("penalty_per_wrong"),
        }
        data = {k: v for k, v in data.items() if v is not None}
        try:
            question = QuestionSetup.model_validate(data)
        except ValidationError as exc:
            had_errors = True
            report.errors += [f"{where}: {describe_error(e)}" for e in exc.errors()]
            continue
        if question.q in seen:
            had_errors = True
            report.errors.append(
                f"{where}: question number {question.q} is already used on row {seen[question.q]}"
            )
            continue
        seen[question.q] = row_no
        questions.append(question)

    if not questions and not had_errors:
        report.errors.append("Questions tab: no questions found")
    return None if had_errors or not questions else questions


# --- entry point ------------------------------------------------------------


def import_event_workbook(path: str | Path) -> ImportReport:
    """Read and validate an event-setup workbook. Never raises for bad content."""
    path = Path(path)
    report = ImportReport(source=path.name)
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # corrupt file, wrong format, missing file
        report.errors.append(f"Could not open {path.name} as an .xlsx workbook ({exc})")
        return report

    try:
        names = {name.strip().lower(): name for name in wb.sheetnames}
        report.tabs_ignored = [
            n for n in wb.sheetnames if n.strip().lower() not in {"event", "questions"}
        ]
        event_ws = wb[names["event"]] if "event" in names else None
        questions_ws = wb[names["questions"]] if "questions" in names else None
        if event_ws is None:
            report.errors.append(f"Missing tab '{EVENT_TAB}'")
        if questions_ws is None:
            report.errors.append(f"Missing tab '{QUESTIONS_TAB}'")

        event_rows: dict[str, int] = {}
        event = _read_event_tab(event_ws, report, event_rows) if event_ws is not None else None
        questions = _read_questions_tab(questions_ws, report) if questions_ws is not None else None
    finally:
        wb.close()

    if event is None or questions is None:
        return report

    mcq = sum((q.points for q in questions), Decimal("0"))
    expected = event.free_response_max + mcq
    if event.total_points != expected:
        report.errors.append(
            f"Event row {event_rows['total_points']}: total_points is "
            f"{_fmt(event.total_points)} but free_response_max "
            f"({_fmt(event.free_response_max)}) + multiple-choice points ({_fmt(mcq)}) "
            f"= {_fmt(expected)}"
        )
        return report

    try:
        report.setup = EventSetup(event=event, questions=questions)
    except ValidationError as exc:  # pragma: no cover - checks above mirror the schema
        report.errors += [describe_error(e) for e in exc.errors()]
    return report
