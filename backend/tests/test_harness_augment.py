"""Fake photos: deterministic, bounded in size, and the recorded page corners are true."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.harness.augment import CONDITIONS, DEFAULT_SIZE, photo_params, photograph
from app.services.event_import import import_event_workbook
from app.services.layout import build_layout
from app.services.sheet_pdf import render_sheet_image

AP = Path(__file__).resolve().parents[2] / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"
DPI = 100  # small page keeps the tests fast
SIZE = (750, 1000)


@pytest.fixture(scope="module")
def sheet() -> tuple[object, np.ndarray]:
    setup = import_event_workbook(AP).setup
    assert setup is not None
    layout = build_layout(setup)
    return layout, render_sheet_image(layout, DPI)


@pytest.mark.parametrize("condition", CONDITIONS)
def test_deterministic_and_bounded(condition: str, sheet: tuple[object, np.ndarray]) -> None:
    _, page = sheet
    a = photograph(page, condition, np.random.default_rng(3), size=SIZE)
    b = photograph(page, condition, np.random.default_rng(3), size=SIZE)
    assert a.jpeg == b.jpeg and a.corners == b.corners and a.params == b.params
    img = a.decode()
    assert img.shape == (SIZE[1], SIZE[0], 3)
    for x, y in a.corners:  # the whole page is in frame
        assert -1 <= x <= SIZE[0] + 1 and -1 <= y <= SIZE[1] + 1, (condition, a.corners)


@pytest.mark.parametrize("condition", CONDITIONS)
def test_different_seeds_differ(condition: str, sheet: tuple[object, np.ndarray]) -> None:
    _, page = sheet
    a = photograph(page, condition, np.random.default_rng(1), size=SIZE)
    b = photograph(page, condition, np.random.default_rng(2), size=SIZE)
    assert a.jpeg != b.jpeg


# Conditions where the printed markers stay sharp enough to locate precisely.
SHARP = ["clean", "rotate_small", "rotate_large", "rotate_90", "rotate_180", "perspective",
         "near", "corner_edge", "clutter", "color_cast", "uneven_light"]  # fmt: skip


@pytest.mark.parametrize("condition", SHARP)
def test_recorded_corners_match_printed_markers(condition: str, sheet: tuple) -> None:
    """Map each marker's layout position through the recorded corners; the detector must
    find that marker there. Proves the truth file's geometry describes the real image."""
    layout, page = sheet
    photo = photograph(page, condition, np.random.default_rng(5), size=DEFAULT_SIZE)
    ph, pw = page.shape
    src = np.array([[0, 0], [pw, 0], [pw, ph], [0, ph]], np.float32)
    homography = cv2.getPerspectiveTransform(src, np.array(photo.corners, np.float32))

    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters(),
    )
    corners, ids, _ = detector.detectMarkers(cv2.cvtColor(photo.decode(), cv2.COLOR_BGR2GRAY))
    assert ids is not None
    found = {int(i): c.reshape(4, 2).mean(axis=0) for i, c in zip(ids.flatten(), corners,
                                                                    strict=True)}  # fmt: skip
    assert set(found) >= {0, 1, 2, 3}, f"{condition}: found markers {sorted(found)}"
    scale = DPI / 72
    for m in layout.markers:
        centre = np.array([[[(m.box.x + m.box.w / 2) * scale, (m.box.y + m.box.h / 2) * scale]]],
                          np.float32)  # fmt: skip
        expected = cv2.perspectiveTransform(centre, homography)[0, 0]
        assert np.linalg.norm(found[m.id] - expected) < 6, (condition, m.id)


def test_conditions_do_what_they_say(sheet: tuple[object, np.ndarray]) -> None:
    _, page = sheet
    rng = np.random.default_rng

    def mean(condition: str, **kw: float) -> float:
        return float(photograph(page, condition, rng(0), size=SIZE, **kw).decode().mean())

    assert mean("low_light", strength=1) < mean("clean") - 40
    jpeg_sizes = [len(photograph(page, c, rng(0), size=SIZE).jpeg) for c in ("clean", "jpeg_heavy")]
    assert jpeg_sizes[1] < jpeg_sizes[0] / 2

    def page_area(condition: str) -> float:
        c = np.array(photograph(page, condition, rng(0), size=SIZE).corners, np.float32)
        return float(cv2.contourArea(c))

    assert page_area("far") < page_area("clean") < page_area("near")
    b, g, r = (
        photograph(page, "color_cast", rng(0), size=SIZE, strength=1)
        .decode()
        .reshape(-1, 3)
        .mean(0)
    )
    assert r > b + 15  # warm


def test_strength_scales_effect() -> None:
    weak = photo_params("rotate_large", np.random.default_rng(0), 0.0)
    strong = photo_params("rotate_large", np.random.default_rng(0), 1.0)
    assert abs(weak["angle"]) < abs(strong["angle"])
    assert photo_params("perspective", np.random.default_rng(0), 1.0)["tilt"] >= 0.29


def test_unknown_condition() -> None:
    with pytest.raises(ValueError, match="unknown condition 'fog'"):
        photo_params("fog", np.random.default_rng(0), 0.5)


@pytest.mark.parametrize("seed", range(12))
def test_corner_edge_keeps_page_large(seed: int, sheet: tuple[object, np.ndarray]) -> None:
    """The page is nudged into frame, not shrunk: one corner hugs the frame edge and the
    page stays about as big as asked."""
    _, page = sheet
    photo = photograph(page, "corner_edge", np.random.default_rng(seed), size=SIZE)
    c = np.array(photo.corners)
    assert (c >= -1).all() and (c[:, 0] <= SIZE[0] + 1).all() and (c[:, 1] <= SIZE[1] + 1).all()
    near_edge = np.minimum(c, np.array(SIZE) - c).min(axis=1)
    assert near_edge.min() < 0.03 * min(SIZE)
    height = np.linalg.norm(c[3] - c[0])
    assert height > 0.75 * SIZE[1]
