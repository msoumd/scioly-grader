"""Dataset builder: reproducible, complete, and small builds are fast."""

import json
import time
from pathlib import Path

import cv2
import pytest

from app.harness.augment import CONDITIONS
from app.harness.dataset import (
    MANIFEST,
    build_dataset,
    resolve_conditions,
    write_contact_sheet,
)
from app.harness.truth import SheetTruth
from app.schemas.event_setup import EventSetup
from app.services.event_import import import_event_workbook

EXAMPLES = Path(__file__).resolve().parents[2] / "event_setups"
SMALL = (600, 800)


def _setup(name: str = "PUSO_2026_AP_event_setup.xlsx") -> EventSetup:
    setup = import_event_workbook(EXAMPLES / name).setup
    assert setup is not None
    return setup


def test_ten_sheets_build_fast_and_complete(tmp_path: Path) -> None:
    start = time.perf_counter()
    manifest = build_dataset(_setup(), tmp_path, 10, dpi=150, size=SMALL)
    assert time.perf_counter() - start < 30
    assert manifest["n"] == 10 and manifest["samples"] == [f"{i:04d}" for i in range(10)]
    assert sum(manifest["counts"].values()) == 10
    assert json.loads((tmp_path / MANIFEST).read_text()) == manifest
    for sid in manifest["samples"]:
        img = cv2.imread(str(tmp_path / f"{sid}.jpg"))
        assert img.shape == (SMALL[1], SMALL[0], 3)
        truth = SheetTruth.load(tmp_path / f"{sid}.json")
        assert truth.sample_id == sid and truth.event_code == "AP"
        assert truth.page_corners is not None and len(truth.page_corners) == 4
        assert truth.augment["condition"] == truth.condition


def test_rebuild_is_byte_identical(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    build_dataset(_setup(), a, 4, conditions=["phone", "shadow"], seed=9, dpi=100, size=SMALL)
    build_dataset(_setup(), b, 4, conditions=["phone", "shadow"], seed=9, dpi=100, size=SMALL)
    for f in sorted(a.iterdir()):
        assert f.read_bytes() == (b / f.name).read_bytes(), f.name


def test_sample_depends_only_on_seed_and_index(tmp_path: Path) -> None:
    """A bigger dataset starts with exactly the same sheets as a smaller one."""
    small, big = tmp_path / "s", tmp_path / "b"
    build_dataset(_setup(), small, 2, conditions=["clean"], dpi=100, size=SMALL)
    build_dataset(_setup(), big, 5, conditions=["clean"], dpi=100, size=SMALL)
    for sid in ("0000", "0001"):
        assert (small / f"{sid}.jpg").read_bytes() == (big / f"{sid}.jpg").read_bytes()


def test_rebuilding_smaller_removes_old_samples(tmp_path: Path) -> None:
    build_dataset(_setup(), tmp_path, 5, conditions=["clean"], dpi=100, size=SMALL)
    build_dataset(_setup(), tmp_path, 2, conditions=["clean"], dpi=100, size=SMALL)
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == ["0000.jpg", "0001.jpg"]


def test_conditions_cycle(tmp_path: Path) -> None:
    build_dataset(_setup(), tmp_path, 6, conditions=["clean", "far", "near"], dpi=100, size=SMALL)
    got = [SheetTruth.load(tmp_path / f"{i:04d}.json").condition for i in range(6)]
    assert got == ["clean", "far", "near"] * 2


def test_any_event_works(tmp_path: Path) -> None:
    manifest = build_dataset(_setup("EXAMPLE_forensics_event_setup.xlsx"), tmp_path, 3,
                             dpi=100, size=SMALL)  # fmt: skip
    assert manifest["event_id"] == "FOR"
    truth = SheetTruth.load(tmp_path / "0000.json")
    assert set(truth.marks) == {25, 45, 49, 57, 58, 59, 60, 62, 63, 68, 69}


def test_contact_sheet(tmp_path: Path) -> None:
    build_dataset(_setup(), tmp_path / "ds", 7, dpi=100, size=SMALL)
    out = tmp_path / "contact.jpg"
    assert write_contact_sheet(tmp_path / "ds", out, count=5, cols=3, thumb=(90, 120)) == 5
    assert cv2.imread(str(out)).shape == (2 * (120 + 26), 270, 3)


def test_resolve_conditions() -> None:
    assert resolve_conditions("all") == list(CONDITIONS)
    assert resolve_conditions(" clean, shadow ") == ["clean", "shadow"]
    with pytest.raises(ValueError, match="unknown condition"):
        resolve_conditions("clean,fog")
    with pytest.raises(ValueError):
        resolve_conditions("")


def test_n_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_dataset(_setup(), tmp_path, 0)
