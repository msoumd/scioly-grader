"""Measure a sheet reader against a labelled dataset, per photo condition.

The number that matters most is the **silent error rate**: questions read wrong *and*
not flagged for a human. A flagged mistake gets fixed on the review screen; a silent
one changes a team's score without anyone noticing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from app.harness.augment import CONDITIONS
from app.harness.dataset import MANIFEST
from app.harness.truth import SheetTruth, bubble_key
from app.schemas.event_setup import LETTERS, EventSetup
from app.schemas.sheet_read import SheetRead
from app.services.scoring import fmt_points, score_sheet

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
_SKIP_JSON = {MANIFEST, "TEMPLATE.json"}
_SAMPLE_ID = re.compile(r"^[\w-]+$")


@dataclass(frozen=True)
class Sample:
    sample_id: str
    image_path: Path
    truth: SheetTruth

    def load_image(self) -> npt.NDArray[np.uint8]:
        img = cv2.imread(str(self.image_path), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"cannot read image {self.image_path}")
        return np.asarray(img, np.uint8)


Reader = Callable[[Sample], SheetRead]


def load_dataset(path: Path) -> tuple[EventSetup, list[Sample]]:
    manifest_path = path / MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError(f"{path} has no {MANIFEST}; is it a harness dataset?")
    setup = EventSetup.model_validate(json.loads(manifest_path.read_text())["setup"])
    samples = []
    for truth_path in sorted(path.glob("*.json")):
        if truth_path.name in _SKIP_JSON or not _SAMPLE_ID.match(truth_path.stem):
            continue
        image = next((truth_path.with_suffix(s) for s in IMAGE_SUFFIXES
                      if truth_path.with_suffix(s).exists()), None)  # fmt: skip
        if image is None:
            raise FileNotFoundError(f"no image next to {truth_path.name}")
        samples.append(Sample(truth_path.stem, image, SheetTruth.load(truth_path)))
    return setup, samples


# --- tallies -------------------------------------------------------------------


@dataclass
class Tally:
    sheets: int = 0
    questions: int = 0
    questions_correct: int = 0
    flagged: int = 0
    silent: int = 0  # wrong and not flagged
    bubbles: int = 0
    bubbles_correct: int = 0
    team_total: int = 0
    team_correct: int = 0
    team_silent: int = 0
    event_read: int = 0
    retakes: int = 0  # sheets the reader asked to photograph again
    score_errors: list[Decimal] = field(default_factory=list)

    @staticmethod
    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 6) if den else None

    def metrics(self) -> dict[str, Any]:
        errs = sorted(self.score_errors)
        p95 = errs[min(len(errs) - 1, int(0.95 * len(errs)))] if errs else None
        return {
            "sheets": self.sheets,
            "questions": self.questions,
            "bubble_accuracy": self._rate(self.bubbles_correct, self.bubbles),
            "question_accuracy": self._rate(self.questions_correct, self.questions),
            "flag_rate": self._rate(self.flagged, self.questions),
            "silent_errors": self.silent,
            "silent_error_rate": self._rate(self.silent, self.questions),
            "team_accuracy": self._rate(self.team_correct, self.team_total),
            "team_silent_errors": self.team_silent,
            "event_read_rate": self._rate(self.event_read, self.sheets),
            "retake_rate": self._rate(self.retakes, self.sheets),
            "score_exact_rate": self._rate(sum(e == 0 for e in errs), len(errs)),
            "score_error_mean": float(sum(errs) / len(errs)) if errs else None,
            "score_error_p95": float(p95) if p95 is not None else None,
            "score_error_max": float(errs[-1]) if errs else None,
        }


@dataclass
class StyleTally:
    bubbles: int = 0
    correct: int = 0


@dataclass
class EvalReport:
    reader: str
    dataset: str
    overall: Tally = field(default_factory=Tally)
    by_condition: dict[str, Tally] = field(default_factory=dict)
    by_style: dict[str, StyleTally] = field(default_factory=dict)
    worst: list[dict[str, Any]] = field(default_factory=list)  # sheets with silent errors

    @property
    def perfect(self) -> bool:
        m = self.overall.metrics()
        return (
            m["silent_errors"] == 0
            and m["team_silent_errors"] == 0
            and m["question_accuracy"] == 1.0
            and m["team_accuracy"] == 1.0
            and m["event_read_rate"] == 1.0
        )

    def to_dict(self) -> dict[str, Any]:
        order = {c: i for i, c in enumerate(CONDITIONS)}
        return {
            "reader": self.reader,
            "dataset": self.dataset,
            "overall": self.overall.metrics(),
            "by_condition": {
                c: t.metrics()
                for c, t in sorted(self.by_condition.items(), key=lambda kv: order.get(kv[0], 99))
            },
            "by_fill_style": {
                s: {"bubbles": t.bubbles, "accuracy": Tally._rate(t.correct, t.bubbles)}
                for s, t in sorted(self.by_style.items())
            },
            "sheets_with_silent_errors": self.worst,
        }

    def to_markdown(self) -> str:
        d = self.to_dict()

        def pct(v: float | None) -> str:
            return "-" if v is None else f"{v * 100:.2f}%"

        def num(v: float | None) -> str:
            return "-" if v is None else f"{v:g}"

        o = d["overall"]
        lines = [
            f"# Reader evaluation: `{self.reader}`",
            "",
            f"Dataset: `{self.dataset}` | {o['sheets']} sheets | {o['questions']} questions",
            "",
            "**Silent errors** (read wrong and *not* flagged for review) are what matter most:",
            f"{o['silent_errors']} ({pct(o['silent_error_rate'])} of questions), "
            f"plus {o['team_silent_errors']} silent team-number errors.",
            "",
            "## By condition",
            "",
            "| Condition | Sheets | Silent error | Question acc. | Bubble acc. | Flagged | "
            "Retake | Team acc. | QR read | Score exact | Score err. max |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        rows = [*d["by_condition"].items(), ("**All**", o)]
        for name, m in rows:
            lines.append(
                f"| {name} | {m['sheets']} | {pct(m['silent_error_rate'])} | "
                f"{pct(m['question_accuracy'])} | {pct(m['bubble_accuracy'])} | "
                f"{pct(m['flag_rate'])} | {pct(m['retake_rate'])} | {pct(m['team_accuracy'])} | "
                f"{pct(m['event_read_rate'])} | {pct(m['score_exact_rate'])} | "
                f"{num(m['score_error_max'])} |"
            )
        lines += ["", "## Bubble accuracy by how it was filled", "",
                  "| Fill style | Bubbles | Accuracy |", "|---|---:|---:|"]  # fmt: skip
        for style, m in d["by_fill_style"].items():
            lines.append(f"| {style} | {m['bubbles']} | {pct(m['accuracy'])} |")
        if self.worst:
            lines += ["", "## Sheets with silent errors (first 20)", "",
                      "| Sample | Condition | Questions |", "|---|---|---|"]  # fmt: skip
            for w in self.worst[:20]:
                lines.append(f"| {w['sample']} | {w['condition']} | {w['questions']} |")
        return "\n".join(lines) + "\n"

    def write(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(self.to_dict(), indent=1) + "\n")
        (out / "report.md").write_text(self.to_markdown())


# --- evaluation ----------------------------------------------------------------


def _score(setup: EventSetup, marks: dict[int, set[str]]) -> Decimal:
    return score_sheet({q.q: marks.get(q.q, set()) for q in setup.questions}, setup).total


def evaluate(setup: EventSetup, samples: list[Sample], reader: Reader, *,
             reader_name: str = "reader", dataset_name: str = "") -> EvalReport:  # fmt: skip
    report = EvalReport(reader=reader_name, dataset=dataset_name)
    for sample in samples:
        truth = sample.truth
        read = reader(sample)
        cond = report.by_condition.setdefault(truth.condition, Tally())
        tallies = (report.overall, cond)
        # A retake request sends the whole sheet back to the grader: everything is flagged.
        flagged = {q.q for q in setup.questions} if read.retake else set(read.flagged)
        team_flagged = read.team_flagged or read.retake
        silent_qs = []

        for t in tallies:
            t.sheets += 1
            t.retakes += read.retake
            t.event_read += (read.event_code, read.sheet_version) == (
                truth.event_code,
                truth.sheet_version,
            )

        for q in setup.questions:
            want, got = truth.marked(q.q), read.marked(q.q)
            right = want == got
            silent = not right and q.q not in flagged
            if silent:
                silent_qs.append(q.q)
            for letter in LETTERS[: q.options]:
                ok = (letter in want) == (letter in got)
                style = truth.fill_styles.get(bubble_key(q.q, letter))
                st = report.by_style.setdefault(style.value if style else "unmarked", StyleTally())
                st.bubbles += 1
                st.correct += ok
                for t in tallies:
                    t.bubbles += 1
                    t.bubbles_correct += ok
            for t in tallies:
                t.questions += 1
                t.questions_correct += right
                t.flagged += q.q in flagged
                t.silent += silent

        true_team = truth.team_number
        if true_team is None:  # ambiguous by design: right answer is "don't guess"
            team_ok = read.team_number is None or team_flagged
        else:
            team_ok = read.team_number == true_team
        for t in tallies:
            t.team_total += 1
            t.team_correct += team_ok
            t.team_silent += not team_ok and not team_flagged

        true_score = _score(setup, {q: set(v) for q, v in truth.marks.items()})
        read_score = _score(setup, {q: set(v) for q, v in read.marks.items()})
        for t in tallies:
            t.score_errors.append(abs(true_score - read_score))
        if silent_qs:
            report.worst.append(
                {
                    "sample": sample.sample_id,
                    "condition": truth.condition,
                    "questions": silent_qs,
                    "score_error": fmt_points(abs(true_score - read_score)),
                }
            )
    return report


def evaluate_dataset(
    path: Path, make_reader: Callable[[EventSetup], Reader], reader_name: str
) -> EvalReport:
    """Load a dataset, make a reader for its event, and evaluate it."""
    setup, samples = load_dataset(path)
    if not samples:
        raise ValueError(f"no labelled samples in {path}")
    return evaluate(
        setup, samples, make_reader(setup), reader_name=reader_name, dataset_name=str(path)
    )
