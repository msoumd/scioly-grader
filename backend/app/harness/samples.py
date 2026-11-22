"""One-off fake sheet photos with exactly the marks you ask for (tests and e2e fixtures)."""

from __future__ import annotations

import numpy as np

from app.harness.augment import DEFAULT_SIZE, photograph
from app.harness.painter import paint_sheet
from app.harness.truth import FillStyle, SheetTruth, bubble_key, team_key
from app.schemas.event_setup import EventSetup
from app.services.layout import LAYOUT_VERSION, SheetLayout, build_layout
from app.services.sheet_pdf import render_sheet_image

DPI = 200
_pages: dict[str, tuple[SheetLayout, np.ndarray]] = {}


def _page(setup: EventSetup) -> tuple[SheetLayout, np.ndarray]:
    key = setup.model_dump_json()
    if key not in _pages:
        layout = build_layout(setup)
        _pages[key] = (layout, render_sheet_image(layout, DPI))
    return _pages[key]


def filled_page(
    setup: EventSetup,
    marks: dict[int, list[str]],
    team: list[list[int]],
    *,
    rng: np.random.Generator,
    styles: dict[str, FillStyle] | None = None,
) -> np.ndarray:
    """The printed page (greyscale, 200 dpi) with these bubbles filled in pencil."""
    layout, page = _page(setup)
    fill = {bubble_key(q, x): FillStyle.solid for q, v in marks.items() for x in v}
    fill |= {team_key(c, d): FillStyle.solid for c, ds in enumerate(team) for d in ds}
    fill |= styles or {}
    truth = SheetTruth(
        sample_id="sample",
        event_code=setup.event.event_id,
        sheet_version=setup.event.sheet_version,
        layout_version=LAYOUT_VERSION,
        marks={q.q: marks.get(q.q, []) for q in setup.questions},
        team_marks=team,
        fill_styles=fill,
    )
    return paint_sheet(page, layout, truth, DPI, rng)


def sheet_photo(
    setup: EventSetup,
    marks: dict[int, list[str]],
    team: list[list[int]],
    *,
    seed: int = 0,
    condition: str = "clean",
    styles: dict[str, FillStyle] | None = None,
    size: tuple[int, int] = DEFAULT_SIZE,
) -> bytes:
    """A fake phone photo (JPEG) of a sheet with exactly these marks and team digits."""
    rng = np.random.default_rng(seed)
    painted = filled_page(setup, marks, team, rng=rng, styles=styles)
    return photograph(painted, condition, rng, size).jpeg


def team_digits(team_number: int, digits: int) -> list[list[int]]:
    """Team number as bubbled digit columns, e.g. 7 with 2 digits -> [[0], [7]]."""
    return [[int(d)] for d in str(team_number).zfill(digits)]
