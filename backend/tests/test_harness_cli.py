"""Harness command line, end to end: build, evaluate, contact sheet, real-photo labels."""

import json
import shutil
from pathlib import Path

import pytest

from app.harness.__main__ import main
from app.harness.truth import SheetTruth

EXAMPLES = Path(__file__).resolve().parents[2] / "event_setups"
AP = EXAMPLES / "PUSO_2026_AP_event_setup.xlsx"
SMALL = ["--dpi", "100", "--size", "600x800"]


def test_build_evaluate_contact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ds = tmp_path / "ds"
    assert main(["build", "--from-xlsx", str(AP), "--n", "5", "--out", str(ds), *SMALL]) == 0
    assert "Building 5 fake sheets for AP" in capsys.readouterr().out
    assert main(["evaluate", "--dataset", str(ds), "--reader", "oracle", "--require-perfect"]) == 0
    assert (ds / "report" / "report.md").exists()
    assert main(["evaluate", "--dataset", str(ds), "--reader", "blank", "--require-perfect"]) == 1
    assert main(["contact-sheet", "--dataset", str(ds), "--count", "3"]) == 0
    assert (ds / "contact_sheet.jpg").exists()


def test_build_with_chosen_conditions(tmp_path: Path) -> None:
    ds = tmp_path / "ds"
    args = ["build", "--from-xlsx", str(AP), "--n", "2", "--conditions", "shadow,far"]
    assert main([*args, "--out", str(ds), *SMALL]) == 0
    assert json.loads((ds / "manifest.json").read_text())["conditions"] == ["shadow", "far"]


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["build", "--n", "2"], 2),  # no event source
        (["build", "--from-xlsx", str(AP), "--event", "AP"], 2),  # two sources
        (["build", "--from-xlsx", str(AP), "--conditions", "fog"], 1),
        (["build", "--from-xlsx", "missing.xlsx"], 1),
        (["evaluate", "--dataset", "nowhere"], 1),
    ],
)
def test_errors(
    argv: list[str], code: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(argv) == code


def test_bad_size_is_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["build", "--from-xlsx", str(AP), "--size", "big"])
    assert exc.value.code == 2


def test_real_photo_labelling_flow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """label-template -> copy a photo + filled-in JSON -> oracle scores 100%."""
    real = tmp_path / "staff" / "AP"
    assert main(["label-template", "--from-xlsx", str(AP), "--out", str(real)]) == 0
    assert main(["label-template", "--from-xlsx", str(AP), "--out", str(real)]) == 2  # no clobber

    # Stand in for a real phone photo with one fake sheet.
    fake = tmp_path / "fake"
    assert main(["build", "--from-xlsx", str(AP), "--n", "1", "--out", str(fake), *SMALL]) == 0
    shutil.copy(fake / "0000.jpg", real / "IMG_1234.jpg")
    label = SheetTruth.load(real / "TEMPLATE.json")
    source = SheetTruth.load(fake / "0000.json")
    label = label.model_copy(update={"sample_id": "IMG_1234", "marks": source.marks,
                                     "team_marks": source.team_marks})  # fmt: skip
    label.save(real / "IMG_1234.json")

    assert main(["evaluate", "--dataset", str(real), "--reader", "oracle",
                 "--require-perfect"]) == 0  # fmt: skip
    report = json.loads((real / "report" / "report.json").read_text())
    assert report["overall"]["sheets"] == 1
    assert list(report["by_condition"]) == ["real"]
