"""Command-line tools for checking imports and scoring before the web app exists.

    uv run python -m app.cli import-event ../event_setups/PUSO_2026_AP_event_setup.xlsx
    uv run python -m app.cli import-event ../event_setups/PUSO_2026_AP_event_setup.xlsx --save
    uv run python -m app.cli import-teams teams.csv --save
    uv run python -m app.cli score-demo AP "1=D,2=C,9=C,D"
    uv run python -m app.cli make-sheet AP                       # from the database
    uv run python -m app.cli make-sheet --from-xlsx ../event_setups/PUSO_2026_AP_event_setup.xlsx

Without ``--save`` the import commands only check the file and print the report.
Exit code: 0 OK, 1 problems found, 2 bad command line.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.services.event_import import import_event_workbook
from app.services.event_store import (
    EventLockedError,
    load_event_setup,
    load_questions,
    save_event,
)
from app.services.layout import SheetCapacityError, build_layout
from app.services.scoring import fmt_points, score_sheet
from app.services.sheet_pdf import render_sheet_pdf, render_sheet_png
from app.services.teams_import import import_teams_csv, save_teams

SessionFactory = Callable[[], Session]

DB_NOT_READY = "Database is not set up yet. Run: uv run alembic upgrade head"

_MARK_ITEM = re.compile(r"(\d+)\s*=\s*([A-Za-z,\s]*?)(?=[,;\s]*\d+\s*=|\s*$)")


def parse_marks(text: str) -> dict[int, set[str]]:
    """``"1=A,2=B,C, 3="`` -> ``{1: {"A"}, 2: {"B", "C"}, 3: set()}``."""
    text = text.strip()
    marks: dict[int, set[str]] = {}
    pos = 0
    for m in _MARK_ITEM.finditer(text):
        between = text[pos : m.start()]
        if between.strip(" ,;"):
            raise ValueError(f"could not read marks near {between.strip()!r}")
        q = int(m.group(1))
        if q in marks:
            raise ValueError(f"question {q} is listed twice")
        marks[q] = {ch.upper() for ch in m.group(2) if ch.isalpha()}
        pos = m.end()
    if text[pos:].strip(" ,;") or not marks:
        raise ValueError(f'could not read marks {text!r}; expected e.g. "1=A,2=B,C"')
    return marks


def _default_session_factory() -> Session:
    from app.db.session import SessionLocal

    return SessionLocal()


def _import_event(args: argparse.Namespace, sessions: SessionFactory) -> int:
    report = import_event_workbook(args.path)
    print(report.to_text())
    if not report.ok or not args.save:
        if report.ok:
            print("\nChecked only. Add --save to write it to the database.")
        return 0 if report.ok else 1
    assert report.setup is not None
    with sessions() as session:
        try:
            result = save_event(session, report.setup, Path(args.path).name)
        except EventLockedError as exc:
            session.rollback()
            print(f"\nNot saved: {exc}")
            return 1
        session.commit()
    print("\n" + result.to_text())
    return 0


def _import_teams(args: argparse.Namespace, sessions: SessionFactory) -> int:
    report = import_teams_csv(args.path)
    print(report.to_text())
    if not report.ok or not args.save:
        if report.ok:
            print("\nChecked only. Add --save to write it to the database.")
        return 0 if report.ok else 1
    with sessions() as session:
        result = save_teams(session, report.teams)
        session.commit()
    print("\n" + result.to_text())
    return 0


def _score_demo(args: argparse.Namespace, sessions: SessionFactory) -> int:
    try:
        marks = parse_marks(args.marks)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    with sessions() as session:
        try:
            questions = load_questions(session, args.event_id)
        except LookupError as exc:
            print(f"Error: {exc}")
            return 1
    try:
        result = score_sheet(marks, questions)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Event {args.event_id}: scoring {len(marks)} answered question(s)")
    print(f"{'q':>4}  {'marked':<10} {'key':<10} {'points':>8}")
    by_q = {q.q: q for q in questions}
    for num in sorted(marks):
        q = by_q[num]
        got = ",".join(sorted(marks[num])) or "-"
        earned = fmt_points(result.per_question[num])
        print(f"{num:>4}  {got:<10} {q.correct_csv:<10} {earned:>4} / {fmt_points(q.points)}")
    unanswered = len(questions) - len(marks)
    print(f"Unanswered: {unanswered} question(s), 0 points")
    print(f"Total: {result.total} / {fmt_points(result.max_total)}")
    return 0


def _make_sheet(args: argparse.Namespace, sessions: SessionFactory) -> int:
    if bool(args.event_id) == bool(args.from_xlsx):
        print("Error: give either an event_id (from the database) or --from-xlsx PATH")
        return 2
    if args.from_xlsx:
        report = import_event_workbook(args.from_xlsx)
        if not report.ok:
            print(report.to_text())
            return 1
        assert report.setup is not None
        setup = report.setup
    else:
        with sessions() as session:
            try:
                setup = load_event_setup(session, args.event_id)
            except LookupError as exc:
                print(f"Error: {exc}")
                return 1
    try:
        layout = build_layout(setup)
    except SheetCapacityError as exc:
        print(f"Error: {exc}")
        return 1

    default = Path("data/generated") / f"{layout.event_id}_v{layout.sheet_version}.pdf"
    out = Path(args.out) if args.out else default
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_sheet_pdf(layout))
    cols = f"{layout.columns} column{'s' if layout.columns != 1 else ''}"
    print(f"Wrote {out} ({len(layout.questions)} questions, {cols})")
    if args.png:
        png = out.with_suffix(".png")
        png.write_bytes(render_sheet_png(layout))
        print(f"Wrote {png}")
    print("Print at 100% / actual size (not 'fit to page').")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import-event", help="check (and optionally save) an event-setup .xlsx")
    p.add_argument("path")
    p.add_argument("--save", action="store_true", help="write the event to the database")
    p.set_defaults(func=_import_event)

    p = sub.add_parser("import-teams", help="check (and optionally save) a teams CSV")
    p.add_argument("path")
    p.add_argument("--save", action="store_true", help="write the teams to the database")
    p.set_defaults(func=_import_teams)

    p = sub.add_parser("score-demo", help='score marks like "1=A,2=B,C" against a saved event')
    p.add_argument("event_id")
    p.add_argument("marks")
    p.set_defaults(func=_score_demo)

    p = sub.add_parser("make-sheet", help="write the printable bubble sheet PDF for an event")
    p.add_argument("event_id", nargs="?", help="a saved event (omit when using --from-xlsx)")
    p.add_argument("--from-xlsx", metavar="PATH", help="build from a setup file, no database")
    p.add_argument("--out", metavar="PATH", help="default: data/generated/<event>_v<version>.pdf")
    p.add_argument("--png", action="store_true", help="also write a 200 dpi PNG preview")
    p.set_defaults(func=_make_sheet)
    return parser


def main(argv: Sequence[str] | None = None, sessions: SessionFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args, sessions or _default_session_factory))
    except (OperationalError, ProgrammingError) as exc:
        if "no such table" in str(exc) or "does not exist" in str(exc):
            print(DB_NOT_READY)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
