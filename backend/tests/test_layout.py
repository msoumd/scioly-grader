"""Sheet geometry: nothing overlaps, everything is on the page, capacity rule, determinism."""

import itertools
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.event_setup import EventSetup
from app.services.event_import import import_event_workbook
from app.services.layout import (
    INCH,
    LAYOUT_VERSION,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PITCHES,
    Box,
    SheetCapacityError,
    SheetLayout,
    build_layout,
)

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "event_setups").glob("*.xlsx"))
GOLDEN = Path(__file__).parent / "golden"


def make_setup(n: int, options: int | list[int] = 5, digits: int = 2, start: int = 1) -> EventSetup:
    opts = options if isinstance(options, list) else [options] * n
    return EventSetup.model_validate(
        {
            "event": {
                "event_id": "SYN",
                "event_name": "Synthetic",
                "tournament": "Test",
                "team_number_digits": digits,
                "total_points": n,
                "free_response_max": 0,
            },
            "questions": [
                {"q": start + i, "points": 1, "options": opts[i], "correct": "A"} for i in range(n)
            ],
        }
    )


def example_setup(path: Path) -> EventSetup:
    report = import_event_workbook(path)
    assert report.setup is not None, report.errors
    return report.setup


def _elements(layout: SheetLayout) -> list[tuple[str, Box]]:
    items = [
        ("header", layout.header_box),
        ("qr", layout.qr_quiet),
        ("name", layout.name_box),
        ("team", layout.team_grid.box),
    ]
    items += [(f"marker {m.id}", m.quiet) for m in layout.markers]
    items += [(f"q{row.q}", row.box) for row in layout.questions]
    return items


def assert_geometry_ok(layout: SheetLayout) -> None:
    content = layout.content_box
    for name, box in _elements(layout):
        if name.startswith("marker"):
            continue  # quiet zone may extend into the margin
        assert content.contains(box), f"{name} {box} leaves the printable area"
    for m in layout.markers:
        assert content.contains(m.box)

    for (a, box_a), (b, box_b) in itertools.combinations(_elements(layout), 2):
        assert not box_a.overlaps(box_b), f"{a} {box_a} overlaps {b} {box_b}"

    for row in layout.questions:
        first = row.bubbles[0].box
        assert row.label_box.right <= first.x, f"q{row.q} label runs into its bubbles"
        for left, right in itertools.pairwise(row.bubbles):
            assert right.cx - left.cx >= 2 * left.r, f"q{row.q} bubbles overlap"
        assert [b.label for b in row.bubbles] == list("ABCDEFGHI"[: len(row.bubbles)])

    team = layout.team_grid
    for column in team.columns:
        for upper, lower in itertools.pairwise(column):
            assert lower.cy - upper.cy >= 2 * upper.r
        assert [b.label for b in column] == [str(d) for d in range(10)]
    for box, column in zip(team.write_in, team.columns, strict=True):
        assert box.bottom <= column[0].box.y


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_lay_out_cleanly(path: Path) -> None:
    setup = example_setup(path)
    layout = build_layout(setup)
    assert_geometry_ok(layout)
    assert [r.q for r in layout.questions] == sorted(q.q for q in setup.questions)
    assert layout.pitch == PITCHES[0]  # examples fit at full spacing
    for row, q in zip(layout.questions, sorted(setup.questions, key=lambda q: q.q), strict=True):
        assert len(row.bubbles) == q.options


@pytest.mark.parametrize(
    ("n", "options"),
    [
        (1, 2),
        (30, 5),
        (54, 5),
        (100, 5),
        (60, 9),
        (100, [2, 3, 4, 5, 5, 4, 3, 5, 5, 4] * 10),
        (40, [9, 2, 7, 4] * 10),
    ],
)
def test_synthetic_geometry(n: int, options: int | list[int]) -> None:
    assert_geometry_ok(build_layout(make_setup(n, options)))


def test_hundred_five_option_questions_fit() -> None:
    layout = build_layout(make_setup(100, 5))
    assert len(layout.questions) == 100
    assert layout.pitch >= PITCHES[-1]


def test_too_many_raises_clear_error() -> None:
    with pytest.raises(SheetCapacityError) as info:
        build_layout(make_setup(200, 9))
    err = info.value
    assert err.total == 200 and 0 < err.fits < 200
    assert f"only {err.fits} fit on one page" in str(err)


def test_hundred_nine_option_questions_fit_or_raise() -> None:
    try:
        layout = build_layout(make_setup(100, 9))
    except SheetCapacityError as err:
        assert err.fits < 100
    else:
        assert_geometry_ok(layout)
        assert len(layout.questions) == 100


def test_shrinks_spacing_before_giving_up() -> None:
    sizes = [build_layout(make_setup(n, 5)).pitch for n in (60, 100, 115)]
    assert sizes[0] == PITCHES[0]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[-1] < PITCHES[0]


def test_large_question_numbers_get_wider_labels() -> None:
    layout = build_layout(make_setup(20, 5, start=995))
    assert_geometry_ok(layout)
    assert layout.questions[-1].q == 1014


@pytest.mark.parametrize("digits", [1, 2, 3, 4])
def test_team_grid_has_one_column_per_digit(digits: int) -> None:
    layout = build_layout(make_setup(54, 5, digits=digits))
    assert layout.team_grid.digits == digits
    assert len(layout.team_grid.columns) == digits == len(layout.team_grid.write_in)
    assert_geometry_ok(layout)


def test_markers_at_corners_with_ids_in_order() -> None:
    layout = build_layout(make_setup(10))
    size = 0.6 * INCH
    expected = {
        0: (MARGIN, MARGIN),
        1: (PAGE_W - MARGIN - size, MARGIN),
        2: (PAGE_W - MARGIN - size, PAGE_H - MARGIN - size),
        3: (MARGIN, PAGE_H - MARGIN - size),
    }
    for m in layout.markers:
        assert (m.box.x, m.box.y) == pytest.approx(expected[m.id])
    assert all(m.box.w == m.box.h == pytest.approx(size) for m in layout.markers)


def test_qr_box_and_payload() -> None:
    layout = build_layout(make_setup(10))
    assert layout.qr_box.w >= 0.9 * INCH
    assert layout.qr_payload == '{"e":"SYN","v":1}'


def test_deterministic() -> None:
    setup = make_setup(77, [5, 4, 6] * 25 + [2, 9])
    assert build_layout(setup).to_json() == build_layout(setup).to_json()


def test_question_order_on_page_is_by_number() -> None:
    setup = make_setup(10)
    shuffled = setup.model_copy(update={"questions": list(reversed(setup.questions))})
    assert build_layout(shuffled).to_json() == build_layout(setup).to_json()


def test_layout_version_recorded() -> None:
    assert build_layout(make_setup(5)).layout_version == LAYOUT_VERSION


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_golden_layout(path: Path) -> None:
    """Any change to sheet geometry shows up here. If it is intended, bump LAYOUT_VERSION
    and regenerate with: UPDATE_GOLDEN=1 uv run pytest tests/test_layout.py"""
    golden = GOLDEN / f"{path.stem}.layout.json"
    actual = build_layout(example_setup(path)).to_json()
    if os.environ.get("UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(actual)
    assert golden.exists(), f"missing {golden.name}; run with UPDATE_GOLDEN=1"
    assert actual == golden.read_text()


def test_total_points_irrelevant_to_layout() -> None:
    a = make_setup(10)
    b = a.model_copy(
        update={"event": a.event.model_copy(update={"total_points": Decimal("500"),
                                                     "free_response_max": Decimal("490")})}
    )  # fmt: skip
    assert build_layout(a).questions == build_layout(b).questions
