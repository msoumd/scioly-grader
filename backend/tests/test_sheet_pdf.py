"""The printed sheet: one Letter page, deterministic, and machine-readable (QR + markers)."""

import json
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytest

from app.services.event_import import import_event_workbook
from app.services.layout import SheetLayout, build_layout
from app.services.sheet_pdf import (
    aruco_cells,
    render_pdf_image,
    render_sheet_image,
    render_sheet_pdf,
    render_sheet_png,
)
from tests.test_layout import make_setup

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "event_setups").glob("*.xlsx"))
DPI = 200


def _layout(path: Path) -> SheetLayout:
    setup = import_event_workbook(path).setup
    assert setup is not None
    return build_layout(setup)


@pytest.fixture(scope="module", params=EXAMPLES, ids=lambda p: p.name)
def rendered(request: pytest.FixtureRequest) -> tuple[SheetLayout, np.ndarray]:
    layout = _layout(request.param)
    return layout, render_sheet_image(layout, DPI)


def test_one_letter_page() -> None:
    pdf = render_sheet_pdf(build_layout(make_setup(54)))
    doc = pdfium.PdfDocument(pdf)
    try:
        assert len(doc) == 1
        assert doc[0].get_size() == pytest.approx((612, 792))
    finally:
        doc.close()


def test_pdf_bytes_deterministic() -> None:
    layout = build_layout(make_setup(40, 4))
    assert render_sheet_pdf(layout) == render_sheet_pdf(layout)


def test_image_size_matches_dpi(rendered: tuple[SheetLayout, np.ndarray]) -> None:
    _, img = rendered
    assert img.shape == (11 * DPI, int(8.5 * DPI))
    assert img.dtype == np.uint8


def test_pure_black_and_white_mostly(rendered: tuple[SheetLayout, np.ndarray]) -> None:
    """No grey fills: apart from anti-aliased edges, pixels are near-black or near-white."""
    _, img = rendered
    mid = np.count_nonzero((img > 60) & (img < 195))
    assert mid / img.size < 0.02


def test_qr_round_trip(rendered: tuple[SheetLayout, np.ndarray]) -> None:
    layout, img = rendered
    text, points, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert text == layout.qr_payload
    assert json.loads(text) == {"e": layout.event_id, "v": layout.sheet_version}
    # Decoded where the layout says it is
    centre = points.reshape(-1, 2).mean(axis=0)
    expected = np.array([layout.qr_box.x + layout.qr_box.w / 2,
                         layout.qr_box.y + layout.qr_box.h / 2]) * DPI / 72  # fmt: skip
    assert np.allclose(centre, expected, atol=4)


def test_markers_found_at_layout_positions(rendered: tuple[SheetLayout, np.ndarray]) -> None:
    layout, img = rendered
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters(),
    )
    corners, ids, _ = detector.detectMarkers(img)
    assert ids is not None
    found = {int(i): c.reshape(4, 2) for i, c in zip(ids.flatten(), corners, strict=True)}
    assert sorted(found) == [0, 1, 2, 3]
    scale = DPI / 72
    for marker in layout.markers:
        b = marker.box
        expected_tl = np.array([b.x, b.y]) * scale
        expected_centre = np.array([b.x + b.w / 2, b.y + b.h / 2]) * scale
        quad = found[marker.id]
        assert np.allclose(quad.mean(axis=0), expected_centre, atol=2), marker.id
        # ArUco reports corners clockwise from the marker's own top-left; an upright page
        # means that corner is the top-left of the box.
        assert np.allclose(quad[0], expected_tl, atol=2), marker.id


def test_bubbles_printed_where_layout_says(rendered: tuple[SheetLayout, np.ndarray]) -> None:
    """Each bubble's outline is dark ink on its circle and the gap just outside is white."""
    layout, img = rendered
    scale = DPI / 72
    sample = layout.questions[:: max(1, len(layout.questions) // 15)]
    bubbles = [b for row in sample for b in row.bubbles]
    bubbles += [b for col in layout.team_grid.columns for b in col]
    for b in bubbles:
        cx, cy, r = b.cx * scale, b.cy * scale, b.r * scale
        ring = [img[round(cy + r * np.sin(a)), round(cx + r * np.cos(a))]
                for a in np.linspace(0, 2 * np.pi, 24, endpoint=False)]  # fmt: skip
        assert np.median(ring) < 128, f"no outline at bubble {b.label} ({b.cx}, {b.cy})"


def test_aruco_cells_have_black_border() -> None:
    for marker_id in range(4):
        cells = aruco_cells(marker_id)
        assert len(cells) == 6
        assert all(cells[0]) and all(cells[-1])
        assert all(row[0] and row[-1] for row in cells)


def test_png_encoding() -> None:
    png = render_sheet_png(build_layout(make_setup(5)), dpi=50)
    assert png.startswith(b"\x89PNG")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert img.shape == (550, 425)


def test_render_pdf_image_greyscale() -> None:
    img = render_pdf_image(render_sheet_pdf(build_layout(make_setup(5))), dpi=36)
    assert img.ndim == 2
