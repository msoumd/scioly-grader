"""Reading sheets: page finding, orientation, QR, decisions, loaders, end-to-end accuracy."""

import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.harness.answers import generate_answers
from app.harness.augment import photograph
from app.harness.painter import paint_sheet
from app.harness.truth import FillStyle, SheetTruth, bubble_key, team_key
from app.schemas.event_setup import EventSetup
from app.services.detection import load_images, read_sheet
from app.services.detection.loader import UnreadableImageError
from app.services.detection.reader import _decide_digit, _decide_question
from app.services.event_import import import_event_workbook
from app.services.layout import SheetLayout, build_layout
from app.services.sheet_pdf import render_sheet_image

EXAMPLES = Path(__file__).resolve().parents[2] / "event_setups"
DPI = 200


def _setup(name: str = "PUSO_2026_AP_event_setup.xlsx") -> EventSetup:
    setup = import_event_workbook(EXAMPLES / name).setup
    assert setup is not None
    return setup


SETUP = _setup()
LAYOUT = build_layout(SETUP)
PAGE = render_sheet_image(LAYOUT, DPI)


def lookup(code: str, version: int) -> EventSetup | None:
    return SETUP if (code, version) == ("AP", 1) else None


def _truth(
    marks: dict[int, list[str]], team: list[list[int]], styles: dict[str, FillStyle] | None = None
) -> SheetTruth:
    fill = {bubble_key(q, x): FillStyle.solid for q, v in marks.items() for x in v}
    fill |= {team_key(c, d): FillStyle.solid for c, ds in enumerate(team) for d in ds}
    fill |= styles or {}
    return SheetTruth(
        sample_id="t",
        event_code="AP",
        sheet_version=1,
        layout_version=1,
        marks={q.q: marks.get(q.q, []) for q in SETUP.questions},
        team_marks=team,
        fill_styles=fill,
    )


def _painted(
    truth: SheetTruth, layout: SheetLayout = LAYOUT, page: np.ndarray = PAGE
) -> np.ndarray:
    return paint_sheet(page, layout, truth, DPI, np.random.default_rng(0))


MARKS = {1: ["D"], 2: ["A"], 9: ["C", "D"], 25: ["B", "D", "E"], 40: ["E"], 54: ["B"]}
TEAM = [[4], [2]]


def _assert_reads(scan, marks=MARKS, team=42) -> None:  # type: ignore[no-untyped-def]
    assert scan.readable, scan.page_flags
    got = {q: r.marked for q, r in scan.questions.items() if r.marked}
    assert got == marks
    assert scan.team_number == team
    assert scan.flagged_questions == []


# --- page finding and orientation ----------------------------------------------


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_any_orientation(turns: int) -> None:
    img = np.rot90(_painted(_truth(MARKS, TEAM)), turns).copy()
    scan = read_sheet(img, lookup)
    _assert_reads(scan)
    assert (scan.event_code, scan.sheet_version) == ("AP", 1)
    assert scan.page_flags == []


def _cover_marker(img: np.ndarray, marker_id: int) -> np.ndarray:
    img = img.copy()
    s = DPI / 72
    b = next(m for m in LAYOUT.markers if m.id == marker_id).quiet
    img[int(b.y * s) : int(b.bottom * s), int(b.x * s) : int(b.right * s)] = 255
    return img


def test_three_markers_still_read_but_flagged() -> None:
    scan = read_sheet(_cover_marker(_painted(_truth(MARKS, TEAM)), 2), lookup)
    _assert_reads(scan)
    assert "marker_missing" in scan.page_flags
    assert scan.markers_found == (0, 1, 3)


def test_two_markers_means_retake() -> None:
    img = _cover_marker(_cover_marker(_painted(_truth(MARKS, TEAM)), 2), 3)
    scan = read_sheet(img, lookup)
    assert not scan.readable and "page_not_found" in scan.page_flags
    read = scan.to_read()
    assert read.retake and read.marks == {} and read.team_flagged


def test_blank_image_is_retake() -> None:
    scan = read_sheet(np.full((800, 600), 255, np.uint8), lookup)
    assert scan.page_flags == ["page_not_found"] and scan.to_read().retake


# --- QR ------------------------------------------------------------------------


def _cover_qr(img: np.ndarray) -> np.ndarray:
    img = img.copy()
    s = DPI / 72
    b = LAYOUT.qr_quiet
    img[int(b.y * s) : int(b.bottom * s), int(b.x * s) : int(b.right * s)] = 255
    return img


def test_qr_missing_uses_hand_picked_event() -> None:
    scan = read_sheet(_cover_qr(_painted(_truth(MARKS, TEAM))), lookup, fallback=SETUP)
    _assert_reads(scan)
    assert "event_unknown" in scan.page_flags and scan.event_code is None


def test_qr_missing_without_fallback_cannot_read() -> None:
    scan = read_sheet(_cover_qr(_painted(_truth(MARKS, TEAM))), lookup)
    assert not scan.readable and "event_unknown" in scan.page_flags
    assert scan.to_read().retake


def test_unknown_event_in_qr() -> None:
    scan = read_sheet(_painted(_truth(MARKS, TEAM)), lambda c, v: None)
    assert scan.event_code == "AP" and "event_unknown" in scan.page_flags
    assert not scan.readable


# --- decisions -------------------------------------------------------------------

LO, HI, RATIO = 0.15, 0.22, 2.5


@pytest.mark.parametrize(
    ("rel", "marked", "flags"),
    [
        ([0.0, 0.0, 0.0], [], ["blank"]),
        ([0.9, 0.0, 0.0], ["A"], []),
        ([0.9, 0.0, 0.18], ["A"], ["ambiguous"]),  # faint mark: a human decides
        ([0.9, 0.85, 0.0], ["A", "B"], []),  # equally dark double mark: read as given
        ([0.9, 0.3, 0.0], ["A", "B"], ["multiple_marks"]),  # one much fainter
        ([0.0, 0.16, 0.0], [], ["ambiguous"]),
        ([0.0, 0.22, 0.0], ["B"], []),  # exactly on the mark line counts
        ([0.0, 0.149, 0.0], [], ["blank"]),
    ],
)
def test_question_decisions(rel: list[float], marked: list[str], flags: list[str]) -> None:
    r = _decide_question(7, ["A", "B", "C"], rel, LO, HI, RATIO)
    assert (r.marked, r.flags) == (marked, flags)
    assert r.needs_review == bool({"ambiguous", "multiple_marks"} & set(flags))
    assert 0 <= r.confidence <= 1


def test_confidence_drops_near_thresholds() -> None:
    sure = _decide_question(1, ["A", "B"], [0.95, 0.0], LO, HI, RATIO).confidence
    close = _decide_question(1, ["A", "B"], [0.24, 0.0], LO, HI, RATIO).confidence
    assert sure == 1.0 and close < 0.5


@pytest.mark.parametrize(
    ("rel", "digit", "flags"),
    [
        ([0.0] * 7 + [0.9, 0.0, 0.0], 7, []),
        ([0.0] * 10, None, ["team_digit_missing"]),
        ([0.9, 0.9] + [0.0] * 8, None, ["team_digit_ambiguous"]),
        ([0.9, 0.17] + [0.0] * 8, None, ["team_digit_unclear"]),
    ],
)
def test_digit_decisions(rel: list[float], digit: int | None, flags: list[str]) -> None:
    d = _decide_digit(0, rel, LO, HI)
    assert (d.digit, d.flags) == (digit, flags)


def test_team_problems_flagged_not_guessed() -> None:
    scan = read_sheet(_painted(_truth(MARKS, [[4], []])), lookup)
    assert scan.team_number is None and "team_digit_missing" in scan.team_flags
    scan = read_sheet(_painted(_truth(MARKS, [[4], [2, 7]])), lookup)
    assert scan.team_number is None and "team_digit_ambiguous" in scan.team_flags


def test_unknown_team_number() -> None:
    scan = read_sheet(_painted(_truth(MARKS, TEAM)), lookup, valid_teams={1, 2, 3})
    assert scan.team_number == 42 and "team_unknown" in scan.team_flags


def test_erasure_reads_blank_light_mark_reads_marked() -> None:
    styles = {bubble_key(3, "A"): FillStyle.erased, bubble_key(40, "E"): FillStyle.light}
    scan = read_sheet(_painted(_truth(MARKS, TEAM, styles)), lookup)
    assert scan.questions[3].marked == [] and not scan.questions[3].needs_review
    assert scan.questions[40].marked == ["E"]


def test_score_and_crop() -> None:
    scan = read_sheet(_painted(_truth(MARKS, TEAM)), lookup)
    # q1 D (right, 1), q2 A (wrong), q9 C,D (right, 1), q25 B,D,E (right, 2),
    # q40 E (key C: wrong), q54 B (right, 1)
    assert scan.mcq_score is not None and float(scan.mcq_score) == 5.0
    crop = scan.crop(25)
    assert crop is not None and crop.shape[0] > 30 and crop.shape[1] > 150
    assert scan.crop(999) is None


def test_other_event_shape() -> None:
    setup = _setup("EXAMPLE_forensics_event_setup.xlsx")
    layout = build_layout(setup)
    marks = {25: ["A"], 49: ["C"], 68: ["D"]}
    styles = {bubble_key(q, v[0]): FillStyle.solid for q, v in marks.items()}
    styles |= {team_key(0, 1): FillStyle.solid, team_key(1, 9): FillStyle.solid}
    truth = SheetTruth(
        sample_id="f",
        event_code="FOR",
        sheet_version=1,
        layout_version=1,
        marks={q.q: marks.get(q.q, []) for q in setup.questions},
        team_marks=[[1], [9]],
        fill_styles=styles,
    )
    img = paint_sheet(render_sheet_image(layout, DPI), layout, truth, DPI, np.random.default_rng(1))
    scan = read_sheet(img, lambda c, v: setup if c == "FOR" else None)
    assert {q: r.marked for q, r in scan.questions.items() if r.marked} == marks
    assert scan.team_number == 19


# --- photos end to end -----------------------------------------------------------

MILD = ["clean", "rotate_small", "rotate_180", "perspective", "shadow", "glare", "phone", "curl"]


@pytest.mark.parametrize("condition", MILD)
def test_photo_round_trip(condition: str) -> None:
    """Fake student + fake phone photo -> read -> no silent errors, score matches."""
    rng = np.random.default_rng(100 + MILD.index(condition))
    answers = generate_answers(SETUP, rng)
    truth = SheetTruth(
        sample_id="p",
        event_code="AP",
        sheet_version=1,
        layout_version=1,
        marks=answers.marks,
        team_marks=answers.team_marks,
        fill_styles=answers.fill_styles,
        strays=answers.strays,
    )
    painted = paint_sheet(PAGE, LAYOUT, truth, DPI, rng)
    photo = photograph(painted, condition, rng)
    scan = read_sheet(photo.decode(), lookup)
    assert scan.readable, scan.page_flags
    for q in SETUP.questions:
        r = scan.questions[q.q]
        assert set(r.marked) == truth.marked(q.q) or r.needs_review, (condition, q.q, r)
    if truth.team_number is not None and not scan.team_flagged:
        assert scan.team_number == truth.team_number


# --- loading -------------------------------------------------------------------


def _jpeg(img: np.ndarray, **kw: object) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=92, **kw)
    return buf.getvalue()


def test_load_jpeg_png_and_downscale() -> None:
    small = cv2.resize(PAGE, (850, 1100))
    jpg = load_images(_jpeg(small))
    assert len(jpg) == 1 and jpg[0].shape == (1100, 850, 3)
    ok, png = cv2.imencode(".png", PAGE)
    big = load_images(png.tobytes())[0]
    assert max(big.shape[:2]) == 2200  # under the 2500 px limit: unchanged
    huge = cv2.resize(PAGE, (3400, 4400))
    assert max(load_images(_jpeg(huge))[0].shape[:2]) == 2500


def test_exif_orientation_applied() -> None:
    img = cv2.resize(PAGE, (400, 520))
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 clockwise to display"
    loaded = load_images(_jpeg(img, exif=exif))[0]
    assert loaded.shape[:2] == (400, 520)


def test_load_heic() -> None:
    import pillow_heif

    heif = pillow_heif.from_pillow(Image.fromarray(cv2.resize(PAGE, (425, 550))).convert("RGB"))
    buf = io.BytesIO()
    heif.save(buf, quality=90)
    loaded = load_images(buf.getvalue(), "IMG_0001.HEIC")
    assert loaded[0].shape == (550, 425, 3)


def test_multipage_pdf_reads_every_page() -> None:
    teams = [[[0], [1]], [[0], [2]], [[0], [3]]]
    pages = [Image.fromarray(_painted(_truth(MARKS, t))).convert("RGB") for t in teams]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    images = load_images(buf.getvalue(), "scans.pdf")
    assert len(images) == 3
    assert [read_sheet(img, lookup).team_number for img in images] == [1, 2, 3]


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"%PDF-1.4 broken"])
def test_unreadable_files(data: bytes) -> None:
    with pytest.raises(UnreadableImageError):
        load_images(data)


def test_pdf_pages_are_identical_when_read_from_many_threads() -> None:
    """PDFium is not thread-safe; the loader serialises it so parallel readers agree."""
    from concurrent.futures import ThreadPoolExecutor

    from app.services.detection.loader import PDFIUM_LOCK

    teams = [[[0], [1]], [[0], [2]], [[0], [3]]]
    pages = [Image.fromarray(_painted(_truth(MARKS, t))).convert("RGB") for t in teams]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    data = buf.getvalue()
    ref = load_images(data, "scans.pdf")
    with ThreadPoolExecutor(4) as pool:
        for got in pool.map(lambda _: load_images(data, "scans.pdf"), range(12)):
            assert all(np.array_equal(a, b) for a, b in zip(ref, got, strict=True))
    assert not PDFIUM_LOCK.locked()
