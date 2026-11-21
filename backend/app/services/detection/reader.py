"""Read one page image into a ``SheetScan``: event, team number, marks, flags and score.

How a bubble is judged:
1. Lighting is divided out, so every pixel is "darkness relative to the paper around it".
2. Each question row is re-centred by up to a few pixels on its printed circles.
3. A bubble's fill = mean darkness inside its inner circle minus the blank level for that
   letter on this page (blank bubbles still hold a printed letter).
4. Fill is compared with this page's own solid-mark level, so a light pencil, a dim photo
   or a blurry photo all scale together.
5. Clearly above ``mark_threshold``: marked. Clearly below ``blank_threshold``: blank.
   In between: the question is flagged for a human.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import cv2
import numpy as np
import numpy.typing as npt

from app.schemas.event_setup import EventSetup
from app.schemas.sheet_read import SheetRead
from app.services.detection.config import DEFAULT_CONFIG, DetectionConfig
from app.services.detection.page import (
    find_markers,
    normalise_lighting,
    read_qr,
    warp_page,
)
from app.services.layout import Bubble, SheetLayout, build_layout
from app.services.scoring import score_sheet

Image = npt.NDArray[np.uint8]
Dark = npt.NDArray[np.float32]
SetupLookup = Callable[[str, int], EventSetup | None]

# Question flags that send a question to the review screen. "blank" is informational.
REVIEW_FLAGS = frozenset({"ambiguous", "multiple_marks"})


@dataclass(frozen=True)
class QuestionRead:
    q: int
    marked: list[str]
    fills: dict[str, float]  # letter -> fill relative to the page's solid-mark level
    confidence: float  # 0 (on a threshold) .. 1 (far from every threshold)
    flags: list[str]

    @property
    def needs_review(self) -> bool:
        return bool(REVIEW_FLAGS & set(self.flags))


@dataclass(frozen=True)
class DigitRead:
    column: int
    digit: int | None
    fills: list[float]  # relative fill for digits 0-9
    flags: list[str]


@dataclass
class SheetScan:
    page_flags: list[str] = field(default_factory=list)
    event_code: str | None = None
    sheet_version: int | None = None
    setup: EventSetup | None = None
    team_number: int | None = None
    team_flags: list[str] = field(default_factory=list)
    digits: list[DigitRead] = field(default_factory=list)
    questions: dict[int, QuestionRead] = field(default_factory=dict)
    mcq_score: Decimal | None = None
    markers_found: tuple[int, ...] = ()
    mark_level: float | None = None  # this page's solid-mark fill (absolute darkness)
    warped: Image | None = None  # straightened page, for the review screen
    layout: SheetLayout | None = None

    @property
    def readable(self) -> bool:
        return self.setup is not None and self.warped is not None

    @property
    def flagged_questions(self) -> list[int]:
        return [q for q, r in self.questions.items() if r.needs_review]

    @property
    def team_flagged(self) -> bool:
        return bool(self.team_flags)

    def to_read(self) -> SheetRead:
        return SheetRead(
            event_code=self.event_code,
            sheet_version=self.sheet_version,
            team_number=self.team_number,
            team_flagged=self.team_flagged or not self.readable,
            marks={q: r.marked for q, r in self.questions.items() if r.marked},
            flagged=self.flagged_questions,
        )

    def crop(self, q: int, pad: int = 6) -> Image | None:
        """The question's row from the straightened page, for the review screen."""
        if self.warped is None or self.layout is None:
            return None
        row = next((r for r in self.layout.questions if r.q == q), None)
        if row is None:
            return None
        s = self.warped.shape[1] / self.layout.page_w
        b = row.box
        y0, y1 = max(0, int(b.y * s) - pad), int(b.bottom * s) + pad
        x0, x1 = max(0, int(b.x * s) - pad), int(b.right * s) + pad
        return self.warped[y0:y1, x0:x1]

    def summary(self) -> str:
        lines = []
        if self.page_flags:
            lines.append("Page flags: " + ", ".join(self.page_flags))
        event = f"{self.event_code} v{self.sheet_version}" if self.event_code else "unknown"
        lines.append(f"Event: {event}")
        team = str(self.team_number) if self.team_number is not None else "not read"
        lines.append(
            f"Team: {team}" + (f"  [{', '.join(self.team_flags)}]" if self.team_flags else "")
        )
        if self.questions:
            for q, r in sorted(self.questions.items()):
                shown = ",".join(r.marked) or "-"
                flags = f"  [{', '.join(r.flags)}]" if r.flags else ""
                lines.append(f"  {q:>4}: {shown:<10} conf {r.confidence:.2f}{flags}")
            lines.append(f"Flagged for review: {len(self.flagged_questions)} question(s)")
        if self.mcq_score is not None and self.setup is not None:
            lines.append(f"Multiple-choice score: {self.mcq_score} / {self.setup.mcq_points_total}")
        return "\n".join(lines)


# --- measurement ---------------------------------------------------------------


def _ring_offsets(r: float, n: int = 32) -> npt.NDArray[np.float64]:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([np.cos(a) * r, np.sin(a) * r], axis=1)


def _sample(dark: Dark, pts: npt.NDArray[np.float64]) -> npt.NDArray[np.float32]:
    h, w = dark.shape
    xs = np.clip(np.rint(pts[..., 0]).astype(int), 0, w - 1)
    ys = np.clip(np.rint(pts[..., 1]).astype(int), 0, h - 1)
    return dark[ys, xs]


def _row_offset(
    dark: Dark, centres: npt.NDArray[np.float64], r: float, search: int
) -> tuple[int, int]:
    """Shift (dx, dy) that best lines a row's printed circles up with the image: match a
    template of the row's rings against the page. Copes with curl and slight warp."""
    pad = int(np.ceil(r)) + 3
    x0, y0 = int(centres[:, 0].min()) - pad, int(centres[:, 1].min()) - pad
    x1, y1 = int(centres[:, 0].max()) + pad, int(centres[:, 1].max()) + pad
    template = np.zeros((y1 - y0, x1 - x0), np.float32)
    for cx, cy in centres:
        cv2.circle(template, (int(round(cx - x0)), int(round(cy - y0))), int(round(r)), 1.0, 2)
    h, w = dark.shape
    rx0, ry0 = max(0, x0 - search), max(0, y0 - search)
    rx1, ry1 = min(w, x1 + search), min(h, y1 + search)
    region = dark[ry0:ry1, rx0:rx1]
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return (0, 0)
    score = cv2.matchTemplate(region, template, cv2.TM_CCORR)
    _, _, _, (bx, by) = cv2.minMaxLoc(score)
    return (rx0 + bx - x0, ry0 + by - y0)


def _disc_means(dark: Dark, centres: npt.NDArray[np.float64], r: float) -> npt.NDArray[np.float64]:
    """Mean darkness inside a disc of radius r around each centre."""
    k = int(np.ceil(r))
    yy, xx = np.mgrid[-k : k + 1, -k : k + 1]
    inside = (xx**2 + yy**2) <= r**2
    offs = np.stack([xx[inside], yy[inside]], axis=1).astype(np.float64)
    pts = centres[:, None, :] + offs[None, :, :]
    return _sample(dark, pts).mean(axis=1).astype(np.float64)


@dataclass(frozen=True)
class _Measured:
    bubbles: list[Bubble]
    centres: npt.NDArray[np.float64]  # aligned, pixels
    raw: npt.NDArray[np.float64]  # mean inner darkness


def _measure_rows(
    dark: Dark, rows: Sequence[Sequence[Bubble]], s: float, config: DetectionConfig
) -> list[_Measured]:
    out = []
    for row in rows:
        centres = np.array([(b.cx * s, b.cy * s) for b in row], np.float64)
        r = row[0].r * s
        pitch = float(np.median(np.diff(centres[:, 0]))) if len(row) > 1 else 2.5 * r
        pitch = pitch if pitch > 0 else float(np.median(np.abs(np.diff(centres[:, 1]))))
        dx, dy = _row_offset(dark, centres, r, max(3, int(config.align_search_frac * pitch)))
        centres = centres + np.array([dx, dy])
        out.append(
            _Measured(list(row), centres, _disc_means(dark, centres, r * config.inner_ratio))
        )
    return out


def _confidence(value: float, lo: float, hi: float) -> float:
    """1 when far from the uncertain band [lo, hi), 0 inside it."""
    if lo <= value < hi:
        return 0.0
    distance = value - hi if value >= hi else lo - value
    return float(min(1.0, distance / max(hi - lo, 1e-6)))


# --- decisions -----------------------------------------------------------------


def _decide_question(
    q: int, letters: list[str], rel: list[float], single_answer: bool, config: DetectionConfig
) -> QuestionRead:
    lo, hi = config.blank_threshold, config.mark_threshold
    marked = [letter for letter, v in zip(letters, rel, strict=True) if v >= hi]
    unsure = [letter for letter, v in zip(letters, rel, strict=True) if lo <= v < hi]
    flags = []
    if unsure:
        flags.append("ambiguous")
    if single_answer and len(marked) >= 2:
        strengths = sorted((v for v in rel if v >= hi), reverse=True)
        if strengths[0] >= config.erasure_ratio * strengths[-1]:
            flags.append("multiple_marks")  # one much darker: the other may be an erasure
    if not marked and not unsure:
        flags.append("blank")
    confidence = min(_confidence(v, lo, hi) for v in rel)
    return QuestionRead(
        q=q,
        marked=marked,
        fills={k: round(v, 3) for k, v in zip(letters, rel, strict=True)},
        confidence=round(confidence, 3),
        flags=flags,
    )


def _decide_digit(column: int, rel: list[float], config: DetectionConfig) -> DigitRead:
    lo, hi = config.team_blank_threshold, config.team_mark_threshold
    marked = [d for d, v in enumerate(rel) if v >= hi]
    unsure = [d for d, v in enumerate(rel) if lo <= v < hi]
    flags = []
    if unsure:
        flags.append("team_digit_unclear")
    if not marked and not unsure:
        flags.append("team_digit_missing")
    if len(marked) >= 2:
        flags.append("team_digit_ambiguous")
    digit = marked[0] if len(marked) == 1 and not unsure else None
    return DigitRead(column=column, digit=digit, fills=[round(v, 3) for v in rel], flags=flags)


# --- entry point ---------------------------------------------------------------


def _to_gray(image: Image) -> Image:
    if image.ndim == 2:
        return image
    return np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), np.uint8)


def read_sheet(
    image: Image,
    lookup: SetupLookup,
    *,
    fallback: EventSetup | None = None,
    valid_teams: set[int] | None = None,
    config: DetectionConfig = DEFAULT_CONFIG,
) -> SheetScan:
    """Read one page. ``lookup(event_code, sheet_version)`` returns the event's setup.
    ``fallback`` is used when the QR cannot be read (the grader picked the event by hand).
    ``valid_teams``, if given, flags team numbers not on the teams list."""
    scan = SheetScan()
    gray = _to_gray(image)

    markers = find_markers(gray)
    scan.markers_found = tuple(sorted(markers))
    if len(markers) < config.min_markers:
        scan.page_flags.append("page_not_found")
        return scan
    if len(markers) < 4:
        scan.page_flags.append("marker_missing")

    warp = warp_page(gray, markers, config.dpi)
    if warp.error_px > 6:
        scan.page_flags.append("page_warp_uncertain")
    scan.warped = warp.page

    qr = read_qr(warp.page, gray, config.dpi)
    setup = None
    if qr is not None:
        scan.event_code, scan.sheet_version = qr
        setup = lookup(*qr)
        if setup is None:
            scan.page_flags.append("event_unknown")
    else:
        scan.page_flags.append("event_unknown")
    if setup is None:
        setup = fallback
    if setup is None:
        return scan
    layout = build_layout(setup)
    scan.setup, scan.layout = setup, layout

    s = config.dpi / 72
    dark = normalise_lighting(warp.page, config)

    q_measured = _measure_rows(dark, [row.bubbles for row in layout.questions], s, config)
    t_measured = _measure_rows(dark, layout.team_grid.columns, s, config)

    # Blank level per printed letter: most bubbles of each letter are empty.
    by_letter: dict[str, list[float]] = {}
    for m in q_measured:
        for b, v in zip(m.bubbles, m.raw, strict=True):
            by_letter.setdefault(b.label, []).append(float(v))
    blank_level = {k: float(np.median(v)) for k, v in by_letter.items()}
    q_fill = [
        [max(0.0, float(v) - blank_level[b.label]) for b, v in zip(m.bubbles, m.raw, strict=True)]
        for m in q_measured
    ]
    team_fill = [[max(0.0, float(v) - float(np.median(m.raw))) for v in m.raw] for m in t_measured]

    every = [v for row in q_fill for v in row] + [v for col in team_fill for v in col]
    candidates = sorted(v for v in every if v >= config.min_mark_level)
    level = (
        float(np.median(candidates[len(candidates) // 2 :]))
        if candidates
        else config.min_mark_level
    )
    level = max(level, config.min_mark_level)
    scan.mark_level = round(level, 4)

    correct = {q.q: len(q.correct) for q in setup.questions}
    for row, fills in zip(layout.questions, q_fill, strict=True):
        rel = [v / level for v in fills]
        scan.questions[row.q] = _decide_question(
            row.q, [b.label for b in row.bubbles], rel, correct[row.q] == 1, config
        )

    scan.digits = [
        _decide_digit(i, [v / level for v in col], config) for i, col in enumerate(team_fill)
    ]
    for d in scan.digits:
        scan.team_flags += [f for f in d.flags if f not in scan.team_flags]
    if all(d.digit is not None for d in scan.digits):
        scan.team_number = int("".join(str(d.digit) for d in scan.digits))
        if valid_teams is not None and scan.team_number not in valid_teams:
            scan.team_flags.append("team_unknown")

    marks = {q: set(r.marked) for q, r in scan.questions.items()}
    scan.mcq_score = score_sheet(marks, setup).total
    return scan
