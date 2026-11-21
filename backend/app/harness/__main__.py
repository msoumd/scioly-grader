"""Fake-sheet harness command line.

    uv run python -m app.harness build --from-xlsx ../event_setups/PUSO_2026_AP_event_setup.xlsx --n 200
    uv run python -m app.harness build --event AP --n 200 --conditions all --out data/harness/AP
    uv run python -m app.harness evaluate --dataset data/harness/AP --reader oracle
    uv run python -m app.harness contact-sheet --dataset data/harness/AP
    uv run python -m app.harness label-template --event AP --out data/real_samples/staff/AP

Exit code: 0 OK, 1 problem (or --require-perfect not met), 2 bad command line.
"""  # noqa: E501

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.harness.augment import DEFAULT_SIZE
from app.harness.dataset import MANIFEST, build_dataset, resolve_conditions, write_contact_sheet
from app.harness.evaluate import evaluate_dataset
from app.harness.readers import READERS
from app.harness.truth import SheetTruth
from app.schemas.event_setup import EventSetup
from app.services.event_import import import_event_workbook
from app.services.layout import LAYOUT_VERSION


class UsageError(Exception):
    pass


def _load_setup(args: argparse.Namespace) -> EventSetup:
    if bool(args.event) == bool(args.from_xlsx):
        raise UsageError("give either --event EVENT_ID (from the database) or --from-xlsx PATH")
    if args.from_xlsx:
        report = import_event_workbook(args.from_xlsx)
        if report.setup is None or not report.ok:
            raise ValueError("event setup has problems:\n" + report.to_text())
        return report.setup
    from app.db.session import SessionLocal
    from app.services.event_store import load_event_setup

    with SessionLocal() as session:
        return load_event_setup(session, args.event)


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must look like 1500x2000") from exc
    if not (200 <= w <= 6000 and 200 <= h <= 6000):
        raise argparse.ArgumentTypeError("width and height must be between 200 and 6000")
    return w, h


def _build(args: argparse.Namespace) -> int:
    setup = _load_setup(args)
    conditions = resolve_conditions(args.conditions)
    out = Path(args.out) if args.out else Path("data/harness") / setup.event.event_id

    def progress(done: int, total: int) -> None:
        if done == total or done % 25 == 0:
            print(f"  {done}/{total}", flush=True)

    print(f"Building {args.n} fake sheets for {setup.event.event_id} in {out} ...")
    manifest = build_dataset(setup, out, args.n, conditions, seed=args.seed, dpi=args.dpi,
                             size=args.size, progress=progress)  # fmt: skip
    print("Conditions: " + ", ".join(f"{k} {v}" for k, v in manifest["counts"].items()))
    print("Teams: " + ", ".join(f"{k} {v}" for k, v in manifest["profiles"].items()))
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    report = evaluate_dataset(dataset, READERS[args.reader], args.reader)
    out = Path(args.out) if args.out else dataset / "report"
    report.write(out)
    m = report.overall.metrics()
    print(f"Reader {args.reader} on {m['sheets']} sheets: question accuracy "
          f"{m['question_accuracy']:.2%}, silent errors {m['silent_errors']} "
          f"({m['silent_error_rate']:.2%}), team accuracy {m['team_accuracy']:.2%}")  # fmt: skip
    print(f"Report: {out / 'report.md'}")
    if args.require_perfect and not report.perfect:
        print("Not perfect (--require-perfect)")
        return 1
    return 0


def _contact_sheet(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    out = Path(args.out) if args.out else dataset / "contact_sheet.jpg"
    used = write_contact_sheet(dataset, out, count=args.count)
    print(f"Wrote {out} ({used} images)")
    return 0


def _label_template(args: argparse.Namespace) -> int:
    setup = _load_setup(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / MANIFEST).exists() and not args.force:
        raise UsageError(f"{out / MANIFEST} already exists (use --force to replace it)")
    ev = setup.event
    manifest = {
        "format": 1,
        "kind": "real",
        "event_id": ev.event_id,
        "sheet_version": ev.sheet_version,
        "layout_version": LAYOUT_VERSION,
        "setup": setup.model_dump(mode="json"),
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n")
    template = SheetTruth(
        sample_id="REPLACE_WITH_PHOTO_NAME",
        event_code=ev.event_id,
        sheet_version=ev.sheet_version,
        layout_version=LAYOUT_VERSION,
        condition="real",
        marks={q.q: [] for q in setup.questions},
        team_marks=[[] for _ in range(ev.team_number_digits)],
    )
    template.save(out / "TEMPLATE.json")
    print(f"Wrote {out / MANIFEST} and {out / 'TEMPLATE.json'}")
    print("For each photo IMG.jpg, copy TEMPLATE.json to IMG.json and fill in what was marked.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.harness",
                                     description="Fake-sheet test harness")  # fmt: skip
    sub = parser.add_subparsers(dest="command", required=True)

    def event_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--event", help="a saved event's id (uses the database)")
        p.add_argument("--from-xlsx", metavar="PATH", help="an event setup file (no database)")

    p = sub.add_parser("build", help="make a labelled dataset of fake phone photos")
    event_args(p)
    p.add_argument("--n", type=int, default=200, help="number of sheets (default 200)")
    p.add_argument("--conditions", default="all", help="'all' or a comma list")
    p.add_argument("--out", help="default: data/harness/<event>")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--dpi", type=int, default=200, help="page render resolution")
    p.add_argument("--size", type=_size, default=DEFAULT_SIZE, help="photo WxH, default 1500x2000")
    p.set_defaults(func=_build)

    p = sub.add_parser("evaluate", help="score a reader against a dataset")
    p.add_argument("--dataset", required=True)
    p.add_argument("--reader", choices=sorted(READERS), default="oracle")
    p.add_argument("--out", help="default: <dataset>/report")
    p.add_argument("--require-perfect", action="store_true", help="exit 1 unless 100%%")
    p.set_defaults(func=_evaluate)

    p = sub.add_parser("contact-sheet", help="tile sample images into one JPEG")
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", help="default: <dataset>/contact_sheet.jpg")
    p.add_argument("--count", type=int, default=20)
    p.set_defaults(func=_contact_sheet)

    p = sub.add_parser("label-template", help="start a folder of real, hand-labelled photos")
    event_args(p)
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=_label_template)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except UsageError as exc:
        print(f"Error: {exc}")
        return 2
    except (ValueError, LookupError, FileNotFoundError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
