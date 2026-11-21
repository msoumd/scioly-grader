"""Where everything sits on a bubble sheet, computed once from an ``EventSetup``.

The PDF renderer (``sheet_pdf.py``) draws only what is here, and the detector (phase 4)
reads only what is here, so the printed page and the reader cannot disagree.

Coordinates are PDF points (1/72 in) with the origin at the **top-left** of a US Letter
page, y growing downward. Every number is rounded to 0.01 pt so the same setup always
gives an identical layout. Bump ``LAYOUT_VERSION`` whenever positions change, so sheets
printed with an older layout can still be read with the matching geometry.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.schemas.event_setup import LETTERS, EventInfo, EventSetup, QuestionSetup

LAYOUT_VERSION = 1

INCH = 72.0
PAGE_W = 8.5 * INCH
PAGE_H = 11 * INCH
MARGIN = 0.5 * INCH

MARKER_SIZE = 0.6 * INCH
MARKER_QUIET = 0.1 * INCH  # white border kept clear around each marker
QR_SIZE = 0.9 * INCH
QR_QUIET = 0.15 * INCH

PITCHES = tuple(round(p * INCH, 2) for p in (0.25, 0.24, 0.23, 0.22, 0.21))
MAX_BUBBLE_D = 0.18 * INCH
MIN_BUBBLE_GAP = 0.045 * INCH
COLUMN_GAP = 0.15 * INCH
GAP = 0.1 * INCH  # spacing between blocks

TEAM_PITCH = 0.25 * INCH
TEAM_LABEL_H = 10.0
NAME_BOX_W = 3.5 * INCH
NAME_BOX_H = 0.35 * INCH
NAME_LABEL_H = 11.0
EPS = 1e-6  # coordinates are rounded to 0.01 pt; ignore float noise below that


def _r(v: float) -> float:
    return round(v, 2)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Box(_Frozen):
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def grow(self, by: float) -> Box:
        return Box(
            x=_r(self.x - by), y=_r(self.y - by), w=_r(self.w + 2 * by), h=_r(self.h + 2 * by)
        )

    def overlaps(self, other: Box) -> bool:
        """True if the boxes share area (touching edges do not count)."""
        e = EPS
        return (
            self.x < other.right - e
            and other.x < self.right - e
            and self.y < other.bottom - e
            and other.y < self.bottom - e
        )

    def contains(self, other: Box) -> bool:
        e = EPS
        return (
            self.x <= other.x + e
            and self.y <= other.y + e
            and other.right <= self.right + e
            and other.bottom <= self.bottom + e
        )


def _box(x: float, y: float, w: float, h: float) -> Box:
    return Box(x=_r(x), y=_r(y), w=_r(w), h=_r(h))


class Bubble(_Frozen):
    label: str  # "A".."I" for questions, "0".."9" for team digits
    cx: float
    cy: float
    r: float

    @property
    def box(self) -> Box:
        return _box(self.cx - self.r, self.cy - self.r, 2 * self.r, 2 * self.r)


class Marker(_Frozen):
    """ArUco DICT_4X4_50 marker. IDs: 0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left."""

    id: int
    box: Box

    @property
    def quiet(self) -> Box:
        return self.box.grow(MARKER_QUIET)


class QuestionRow(_Frozen):
    q: int
    label_box: Box  # where the question number is printed (right-aligned)
    bubbles: list[Bubble]

    @property
    def box(self) -> Box:
        last = self.bubbles[-1].box
        return _box(
            self.label_box.x, self.label_box.y, last.right - self.label_box.x, self.label_box.h
        )


class TeamGrid(_Frozen):
    digits: int
    box: Box  # whole block, including the label
    write_in: list[Box]  # one handwriting box above each digit column
    columns: list[list[Bubble]]  # columns[digit position][value 0-9]


class SheetLayout(_Frozen):
    layout_version: int = LAYOUT_VERSION
    page_w: float = PAGE_W
    page_h: float = PAGE_H
    event_id: str
    sheet_version: int
    title: str
    subtitle: str
    header_box: Box
    qr_payload: str
    qr_box: Box
    markers: list[Marker]
    name_box: Box
    team_grid: TeamGrid
    pitch: float
    bubble_r: float
    columns: int
    questions: list[QuestionRow]

    @property
    def content_box(self) -> Box:
        return _box(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN)

    @property
    def qr_quiet(self) -> Box:
        return self.qr_box.grow(QR_QUIET)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"


class SheetCapacityError(ValueError):
    def __init__(self, event_id: str, total: int, fits: int) -> None:
        self.total, self.fits = total, fits
        super().__init__(
            f"Event {event_id} has {total} bubble questions but only {fits} fit on one page "
            f"with these option counts. Remove questions or use fewer options per question."
        )


# --- pieces -----------------------------------------------------------------


def qr_payload(event_id: str, sheet_version: int) -> str:
    return json.dumps({"e": event_id, "v": sheet_version}, separators=(",", ":"))


def _markers() -> list[Marker]:
    far_x = PAGE_W - MARGIN - MARKER_SIZE
    far_y = PAGE_H - MARGIN - MARKER_SIZE
    corners = [(MARGIN, MARGIN), (far_x, MARGIN), (far_x, far_y), (MARGIN, far_y)]
    return [
        Marker(id=i, box=_box(x, y, MARKER_SIZE, MARKER_SIZE)) for i, (x, y) in enumerate(corners)
    ]


def _format_date(info: EventInfo) -> str:
    return f"{info.date:%B} {info.date.day}, {info.date.year}" if info.date else ""


def _team_grid(digits: int, right: float, bottom: float) -> TeamGrid:
    col_w = TEAM_PITCH
    width = max(digits * col_w, 0.75 * INCH)  # room for the "Team number" label
    height = TEAM_LABEL_H + TEAM_PITCH + 2 + 10 * TEAM_PITCH
    x0, y0 = right - width, bottom - height
    cols_x = x0 + (width - digits * col_w) / 2
    write_y = y0 + TEAM_LABEL_H
    write_in = [
        _box(cols_x + i * col_w + 1, write_y, col_w - 2, TEAM_PITCH - 2) for i in range(digits)
    ]
    r = _r(MAX_BUBBLE_D / 2)
    first_cy = write_y + TEAM_PITCH + 2 + TEAM_PITCH / 2
    columns = [
        [
            Bubble(
                label=str(v),
                cx=_r(cols_x + i * col_w + col_w / 2),
                cy=_r(first_cy + v * TEAM_PITCH),
                r=r,
            )
            for v in range(10)
        ]
        for i in range(digits)
    ]
    return TeamGrid(
        digits=digits, box=_box(x0, y0, width, height), write_in=write_in, columns=columns
    )


def _label_width(questions: Sequence[QuestionSetup]) -> float:
    widest = max(len(str(q.q)) for q in questions)
    return 0.12 * INCH + widest * 5.5


def _max_rows(pitch: float, area: Box) -> int:
    return math.floor(area.h / pitch)


def _pack(
    questions: Sequence[QuestionSetup], pitch: float, area: Box, grid: Box, cap: int
) -> tuple[list[QuestionRow], int, int]:
    """Fill columns top to bottom (at most ``cap`` rows each), left to right. Columns that
    would run into the team grid stop above it.
    Returns (rows, columns used, number of questions placed)."""
    label_w = _label_width(questions)
    r = _r(min(MAX_BUBBLE_D, pitch - MIN_BUBBLE_GAP) / 2)
    full_rows = min(cap, _max_rows(pitch, area))
    short_rows = min(full_rows, math.floor((grid.y - GAP - area.y) / pitch))

    def width(chunk: Sequence[QuestionSetup]) -> float:
        return label_w + max(q.options for q in chunk) * pitch

    rows: list[QuestionRow] = []
    x, i, ncols = area.x, 0, 0
    while i < len(questions):
        chunk = questions[i : i + full_rows]
        if x + width(chunk) > grid.x - GAP:
            chunk = questions[i : i + short_rows]
        if not chunk or x + width(chunk) > area.right:
            break
        for row_i, q in enumerate(chunk):
            top = area.y + row_i * pitch
            cy = top + pitch / 2
            bx = x + label_w
            rows.append(
                QuestionRow(
                    q=q.q,
                    label_box=_box(x, top, label_w - 0.06 * INCH, pitch),
                    bubbles=[
                        Bubble(label=LETTERS[k], cx=_r(bx + k * pitch + pitch / 2), cy=_r(cy), r=r)
                        for k in range(q.options)
                    ],
                )
            )
        x += width(chunk) + COLUMN_GAP
        i += len(chunk)
        ncols += 1
    return rows, ncols, i


# --- entry point ------------------------------------------------------------


def build_layout(setup: EventSetup) -> SheetLayout:
    """Lay out one Letter page. Uses the largest bubble spacing that fits; raises
    ``SheetCapacityError`` if even the tightest allowed spacing cannot fit every question."""
    info = setup.event
    questions = sorted(setup.questions, key=lambda q: q.q)
    markers = _markers()

    qr_x = markers[1].quiet.x - QR_QUIET - QR_SIZE
    qr_box = _box(qr_x, MARGIN + QR_QUIET, QR_SIZE, QR_SIZE)
    header_x = markers[0].quiet.right + GAP
    header_box = _box(header_x, MARGIN, qr_x - QR_QUIET - GAP - header_x, QR_SIZE)

    name_top = qr_box.bottom + QR_QUIET + NAME_LABEL_H
    name_box = _box(MARGIN, name_top, NAME_BOX_W, NAME_BOX_H)

    area_top = name_box.bottom + GAP + 4
    area_bottom = markers[3].quiet.y - GAP / 2
    area = _box(MARGIN, area_top, PAGE_W - 2 * MARGIN, area_bottom - area_top)
    grid = _team_grid(info.team_number_digits, area.right, area.bottom)

    n = len(questions)
    placed = 0
    for pitch in PITCHES:
        rows, ncols, placed = _pack(questions, pitch, area, grid.box, _max_rows(pitch, area))
        if placed == n:
            # Balance: the fewest rows per column that still fits, so columns come out even.
            for cap in range(math.ceil(n / ncols), _max_rows(pitch, area)):
                balanced = _pack(questions, pitch, area, grid.box, cap)
                if balanced[2] == n:
                    rows, ncols, placed = balanced
                    break
            break
    else:
        raise SheetCapacityError(info.event_id, n, placed)

    date = _format_date(info)
    return SheetLayout(
        event_id=info.event_id,
        sheet_version=info.sheet_version,
        title=info.event_name,
        subtitle=" | ".join(p for p in (info.tournament, date) if p),
        header_box=header_box,
        qr_payload=qr_payload(info.event_id, info.sheet_version),
        qr_box=qr_box,
        markers=markers,
        name_box=name_box,
        team_grid=grid,
        pitch=pitch,
        bubble_r=rows[0].bubbles[0].r,
        columns=ncols,
        questions=rows,
    )
