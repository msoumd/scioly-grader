"""Marks land exactly where the layout says, and nowhere else."""

from pathlib import Path

import numpy as np
import pytest

from app.harness.answers import generate_answers
from app.harness.painter import bubble_for_key, paint_mark, paint_sheet
from app.harness.truth import FillStyle, SheetTruth
from app.services.event_import import import_event_workbook
from app.services.layout import SheetLayout, build_layout
from app.services.sheet_pdf import render_sheet_image

DPI = 150
EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "event_setups").glob("*.xlsx"))


@pytest.fixture(scope="module", params=EXAMPLES, ids=lambda p: p.stem)
def page(request: pytest.FixtureRequest) -> tuple[SheetLayout, np.ndarray, SheetTruth]:
    setup = import_event_workbook(request.param).setup
    assert setup is not None
    layout = build_layout(setup)
    ans = generate_answers(setup, np.random.default_rng(11))
    truth = SheetTruth(
        sample_id="t",
        event_code=layout.event_id,
        sheet_version=1,
        layout_version=layout.layout_version,
        marks=ans.marks,
        team_marks=ans.team_marks,
        fill_styles=ans.fill_styles,
        strays=3,
    )
    return layout, render_sheet_image(layout, DPI), truth


def _inside(img: np.ndarray, cx: float, cy: float, r: float) -> float:
    """Mean brightness of the inner 60% of a bubble (pixel coords)."""
    yy, xx = np.ogrid[: img.shape[0], : img.shape[1]]
    disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= (0.6 * r) ** 2
    return float(img[disc].mean())


def test_marks_only_where_layout_says(page: tuple[SheetLayout, np.ndarray, SheetTruth]) -> None:
    layout, clean, truth = page
    painted = paint_sheet(clean, layout, truth, DPI, np.random.default_rng(0))
    s = DPI / 72
    touched = {bubble_for_key(layout, k) for k in truth.fill_styles}
    all_bubbles = [b for row in layout.questions for b in row.bubbles]
    all_bubbles += [b for col in layout.team_grid.columns for b in col]
    for b in all_bubbles:
        before = _inside(clean, b.cx * s, b.cy * s, b.r * s)
        after = _inside(painted, b.cx * s, b.cy * s, b.r * s)
        if b in touched:
            assert after < before - 8, f"no mark painted at {b}"
        else:
            assert after == pytest.approx(before, abs=0.5), f"unexpected ink at {b}"


def test_solid_darker_than_light_darker_than_erased() -> None:
    blank = np.full((80, 80), 255, np.uint8)
    levels = {}
    for style in (FillStyle.solid, FillStyle.light, FillStyle.erased):
        img = blank.copy()
        paint_mark(img, 40, 40, 13, style, np.random.default_rng(5))
        levels[style] = _inside(img, 40, 40, 13)
    assert levels[FillStyle.solid] < 100
    assert levels[FillStyle.solid] < levels[FillStyle.light] < levels[FillStyle.erased]
    assert levels[FillStyle.erased] > 185  # faint: should read as blank


@pytest.mark.parametrize("style", list(FillStyle))
def test_every_style_stays_near_its_bubble(style: FillStyle) -> None:
    img = np.full((200, 200), 255, np.uint8)
    paint_mark(img, 100, 100, 13, style, np.random.default_rng(2))
    ys, xs = np.nonzero(img < 250)
    assert len(xs) > 0
    assert np.hypot(xs - 100, ys - 100).max() < 13 * 1.6


def test_painting_is_deterministic(page: tuple[SheetLayout, np.ndarray, SheetTruth]) -> None:
    layout, clean, truth = page
    a = paint_sheet(clean, layout, truth, DPI, np.random.default_rng(4))
    b = paint_sheet(clean, layout, truth, DPI, np.random.default_rng(4))
    assert np.array_equal(a, b)
    assert not np.array_equal(clean, a)  # and the clean page is left untouched


def test_bubble_for_key(page: tuple[SheetLayout, np.ndarray, SheetTruth]) -> None:
    layout, _, _ = page
    row = layout.questions[0]
    assert bubble_for_key(layout, f"{row.q}:B") == row.bubbles[1]
    assert bubble_for_key(layout, "T0:7") == layout.team_grid.columns[0][7]
