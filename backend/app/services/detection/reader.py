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
from dataclasses import dataclass, field, replace
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
REVIEW_FLAGS = frozenset({"ambiguous", "multiple_marks", "alignment_uncertain"})


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
    sharpness: float | None = None  # median edge strength on printed bubble outlines
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
            retake=not self.readable,
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
    edges: Dark,
    centres: npt.NDArray[np.float64],
    r: float,
    search: int,
    around: tuple[int, int] = (0, 0),
) -> tuple[int, int]:
    """Shift (dx, dy) that best lines a row's printed circles up with the page: match a
    template of the row's ring outlines against the page's edge map (normalised, so dark
    filled bubbles do not pull the match). Copes with curl and slight warp."""
    pad = int(np.ceil(r)) + 3
    # Template of the row's rings, in its own frame (top-left = first centre minus pad).
    tx0, ty0 = int(centres[:, 0].min()) - pad, int(centres[:, 1].min()) - pad
    tx1, ty1 = int(centres[:, 0].max()) + pad, int(centres[:, 1].max()) + pad
    template = np.zeros((ty1 - ty0, tx1 - tx0), np.float32)
    for cx, cy in centres:
        cv2.circle(template, (int(round(cx - tx0)), int(round(cy - ty0))), int(round(r)), 1.0, 2)
    # Search window: the template placed at the predicted offset, +/- search.
    px, py = around
    h, w = edges.shape
    rx0, ry0 = max(0, tx0 + px - search), max(0, ty0 + py - search)
    rx1, ry1 = min(w, tx1 + px + search), min(h, ty1 + py + search)
    region = edges[ry0:ry1, rx0:rx1]
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return around
    score = cv2.matchTemplate(region, template, cv2.TM_CCORR_NORMED)
    _, _, _, (bx, by) = cv2.minMaxLoc(score)
    return (rx0 + bx - tx0, ry0 + by - ty0)


def _disc_pixels(dark: Dark, centres: npt.NDArray[np.float64], r: float) -> Dark:
    """Darkness of every pixel inside a disc of radius r around each centre (n x pixels)."""
    k = int(np.ceil(r))
    yy, xx = np.mgrid[-k : k + 1, -k : k + 1]
    inside = (xx**2 + yy**2) <= r**2
    offs = np.stack([xx[inside], yy[inside]], axis=1).astype(np.float64)
    pts = centres[:, None, :] + offs[None, :, :]
    return np.asarray(_sample(dark, pts), np.float32)


@dataclass(frozen=True)
class _Measured:
    bubbles: list[Bubble]
    centres: npt.NDArray[np.float64]  # aligned, pixels
    pixels: Dark  # inner-disc darkness samples, one row per bubble
    offset: tuple[int, int] = (0, 0)
    edge_hit: bool = False  # alignment needed the whole search range: don't trust it

    @property
    def raw(self) -> npt.NDArray[np.float64]:
        """Mean inner darkness per bubble."""
        return np.asarray(self.pixels.mean(axis=1), np.float64)

    def coverage(self, cut: float) -> npt.NDArray[np.float64]:
        """Share of inner-disc pixels darker than ``cut``, per bubble."""
        return np.asarray((self.pixels > cut).mean(axis=1), np.float64)


def edge_map(dark: Dark) -> Dark:
    """Gradient magnitude: strong on printed circle outlines and mark edges."""
    gx = cv2.Sobel(dark, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(dark, cv2.CV_32F, 0, 1, ksize=3)
    return np.asarray(cv2.magnitude(gx, gy), np.float32)


def _measure_row(
    dark: Dark,
    edges: Dark,
    row: Sequence[Bubble],
    s: float,
    config: DetectionConfig,
    around: tuple[int, int],
    search_frac: float | None = None,
) -> _Measured:
    centres = np.array([(b.cx * s, b.cy * s) for b in row], np.float64)
    r = row[0].r * s
    steps = np.abs(np.diff(centres, axis=0)).max(axis=1) if len(row) > 1 else np.array([2.5 * r])
    frac = config.align_search_frac if search_frac is None else search_frac
    search = max(3, int(frac * float(np.median(steps))))
    dx, dy = _row_offset(edges, centres, r, search, around)
    edge = max(abs(dx - around[0]), abs(dy - around[1])) >= search - 1
    aligned = centres + np.array([dx, dy])
    pixels = _disc_pixels(dark, aligned, r * config.inner_ratio)
    return _Measured(list(row), aligned, pixels, (dx, dy), edge)


def _measure_questions(
    dark: Dark, edges: Dark, layout: SheetLayout, s: float, config: DetectionConfig
) -> list[_Measured]:
    """Rows are tracked down each printed column: every row's search starts from the row
    above's offset, so a gradual shift (curled paper) is followed rather than lost."""
    results: dict[int, _Measured] = {}
    columns: dict[float, list[int]] = {}
    for i, row in enumerate(layout.questions):
        columns.setdefault(row.label_box.x, []).append(i)
    column_start = (0, 0)
    for _, indices in sorted(columns.items()):
        around = column_start
        ordered = sorted(indices, key=lambda k: layout.questions[k].label_box.y)
        for n, i in enumerate(ordered):
            # A column's first row gets a wider search: nothing above it to follow yet.
            frac = config.first_row_search_frac if n == 0 else None
            m = _measure_row(dark, edges, layout.questions[i].bubbles, s, config, around, frac)
            results[i] = m
            around = m.offset
            if n == 0:
                column_start = m.offset
    return [results[i] for i in range(len(layout.questions))]


def _measure_team(
    dark: Dark, edges: Dark, layout: SheetLayout, s: float, config: DetectionConfig,
    questions: list[_Measured],
) -> list[_Measured]:  # fmt: skip
    """Each team column starts from the offset of the nearest question row."""
    out = []
    for column in layout.team_grid.columns:
        cx, cy = column[0].cx * s, column[0].cy * s
        nearest = min(
            questions,
            key=lambda m: float(np.hypot(*(m.centres.mean(axis=0) - (cx, cy)))),
            default=None,
        )
        around = nearest.offset if nearest else (0, 0)
        out.append(_measure_row(dark, edges, column, s, config, around))
    return out


def _sharpness(edges: Dark, measured: Sequence[_Measured], s: float) -> float:
    """How crisp the printed bubble outlines are: median edge strength on the rings."""
    angles = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    ring = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    values = []
    for m in measured:
        r = m.bubbles[0].r * s
        pts = m.centres[:, None, :] + ring[None, :, :] * r
        values.append(np.median(_sample(edges, pts), axis=1))
    return float(np.median(np.concatenate(values))) if values else 0.0


def _confidence(value: float, lo: float, hi: float) -> float:
    """1 when far from the uncertain band [lo, hi), 0 inside it."""
    if lo <= value < hi:
        return 0.0
    distance = value - hi if value >= hi else lo - value
    return float(min(1.0, distance / max(hi - lo, 1e-6)))


# --- decisions -----------------------------------------------------------------


def _decide_question(
    q: int,
    letters: list[str],
    rel: list[float],
    single_answer: bool,
    config: DetectionConfig,
    hi: float,
) -> QuestionRead:
    lo = config.blank_threshold
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


def _decide_digit(column: int, rel: list[float], config: DetectionConfig, hi: float) -> DigitRead:
    lo = config.team_blank_threshold
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

    edges = edge_map(dark)
    smooth = np.asarray(cv2.GaussianBlur(dark, (0, 0), config.coverage_smooth_px), np.float32)
    q_measured = _measure_questions(smooth, edges, layout, s, config)
    t_measured = _measure_team(smooth, edges, layout, s, config, q_measured)

    scan.sharpness = round(_sharpness(edges, q_measured + t_measured, s), 3)
    blurry = scan.sharpness < config.blurry_sharpness
    if blurry:
        scan.page_flags.append("image_blurry")
    q_hi = config.blurry_mark_threshold if blurry else config.mark_threshold
    t_hi = config.blurry_mark_threshold if blurry else config.team_mark_threshold

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

    # Second measure: how much of the bubble holds real pencil (darker than a fraction of
    # this page's solid level). A partial fill or light scribble has a patch of real
    # pencil; an erasure is faint everywhere. Each bubble's score is the larger of the two.
    cut = config.coverage_cut * level
    cov_by_letter: dict[str, list[float]] = {}
    q_cov = [m.coverage(cut) for m in q_measured]
    for m, cov in zip(q_measured, q_cov, strict=True):
        for b, c in zip(m.bubbles, cov, strict=True):
            cov_by_letter.setdefault(b.label, []).append(float(c))
    cov_blank = {k: float(np.median(v)) for k, v in cov_by_letter.items()}
    q_score = [
        [
            max(f / level, max(0.0, float(c) - cov_blank[b.label]))
            for b, f, c in zip(m.bubbles, fills, cov, strict=True)
        ]
        for m, fills, cov in zip(q_measured, q_fill, q_cov, strict=True)
    ]
    team_score = []
    for m, fills in zip(t_measured, team_fill, strict=True):
        cov = m.coverage(cut)
        base = float(np.median(cov))
        team_score.append(
            [max(f / level, max(0.0, float(c) - base)) for f, c in zip(fills, cov, strict=True)]
        )

    correct = {q.q: len(q.correct) for q in setup.questions}
    for row, rel, m in zip(layout.questions, q_score, q_measured, strict=True):
        decided = _decide_question(
            row.q, [b.label for b in row.bubbles], rel, correct[row.q] == 1, config, q_hi
        )
        if m.edge_hit:
            decided = replace(decided, flags=[*decided.flags, "alignment_uncertain"])
        scan.questions[row.q] = decided

    if any(m.edge_hit for m in t_measured):
        scan.team_flags.append("team_alignment_uncertain")
    scan.digits = [_decide_digit(i, col, config, t_hi) for i, col in enumerate(team_score)]
    for d in scan.digits:
        scan.team_flags += [f for f in d.flags if f not in scan.team_flags]
    if all(d.digit is not None for d in scan.digits):
        scan.team_number = int("".join(str(d.digit) for d in scan.digits))
        if valid_teams is not None and scan.team_number not in valid_teams:
            scan.team_flags.append("team_unknown")

    marks = {q: set(r.marked) for q, r in scan.questions.items()}
    scan.mcq_score = score_sheet(marks, setup).total
    return scan
