"""The evaluator must be right before it is used to judge the detector."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.harness.dataset import build_dataset
from app.harness.evaluate import Sample, evaluate, evaluate_dataset, load_dataset
from app.harness.readers import READERS, blank_reader, oracle_reader
from app.schemas.event_setup import LETTERS, EventSetup
from app.schemas.sheet_read import SheetRead
from app.services.event_import import import_event_workbook
from app.services.scoring import score_sheet

AP = Path(__file__).resolve().parents[2] / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, EventSetup, list[Sample]]:
    setup = import_event_workbook(AP).setup
    assert setup is not None
    out = tmp_path_factory.mktemp("ds")
    build_dataset(setup, out, 24, dpi=100, size=(600, 800))
    loaded_setup, samples = load_dataset(out)
    assert loaded_setup == setup
    return out, setup, samples


def test_oracle_is_perfect(dataset: tuple[Path, EventSetup, list[Sample]]) -> None:
    path, _, _ = dataset
    report = evaluate_dataset(path, READERS["oracle"], "oracle")
    m = report.overall.metrics()
    assert report.perfect
    assert m["bubble_accuracy"] == m["question_accuracy"] == m["team_accuracy"] == 1.0
    assert m["silent_errors"] == 0 and m["flag_rate"] == 0.0
    assert m["score_error_max"] == 0.0 and m["score_exact_rate"] == 1.0
    assert all(t.metrics()["question_accuracy"] == 1.0 for t in report.by_condition.values())
    assert report.worst == []


def test_blank_reader_numbers(dataset: tuple[Path, EventSetup, list[Sample]]) -> None:
    _, setup, samples = dataset
    report = evaluate(setup, samples, blank_reader)
    m = report.overall.metrics()

    n_q = len(samples) * len(setup.questions)
    answered = sum(bool(s.truth.marks[q.q]) for s in samples for q in setup.questions)
    marked_bubbles = sum(len(s.truth.marks[q.q]) for s in samples for q in setup.questions)
    total_bubbles = len(samples) * sum(q.options for q in setup.questions)
    ambiguous_teams = sum(s.truth.team_number is None for s in samples)
    zero_scores = sum(
        score_sheet({q: set(v) for q, v in s.truth.marks.items()}, setup).total == 0
        for s in samples
    )

    assert not report.perfect
    assert m["questions"] == n_q
    assert m["silent_errors"] == answered  # every answered question missed, none flagged
    assert m["question_accuracy"] == pytest.approx((n_q - answered) / n_q, abs=1e-6)
    assert m["bubble_accuracy"] == pytest.approx(1 - marked_bubbles / total_bubbles, abs=1e-6)
    assert m["team_accuracy"] == pytest.approx(ambiguous_teams / len(samples), abs=1e-6)
    assert m["team_silent_errors"] == len(samples) - ambiguous_teams
    assert m["event_read_rate"] == 0.0
    assert m["score_exact_rate"] == pytest.approx(zero_scores / len(samples), abs=1e-6)
    assert len(report.worst) == sum(1 for s in samples if any(s.truth.marks.values()))


def _wrong_reader(setup: EventSetup):  # type: ignore[no-untyped-def]
    """Gets every 3rd question wrong; flags the wrong ones only when q is even."""

    def read(sample: Sample) -> SheetRead:
        base = oracle_reader(sample)
        marks = {q: list(v) for q, v in base.marks.items()}
        flagged = []
        for q in setup.questions:
            if q.q % 3 == 0:
                want = sample.truth.marked(q.q)
                letters = LETTERS[: q.options]
                marks[q.q] = [letters[0]] if want != {letters[0]} else [letters[1]]
                if q.q % 2 == 0:
                    flagged.append(q.q)
        return base.model_copy(update={"marks": marks, "flagged": flagged})

    return read


def test_wrong_reader_silent_errors_counted(dataset: tuple[Path, EventSetup, list[Sample]]) -> None:
    _, setup, samples = dataset
    report = evaluate(setup, samples, _wrong_reader(setup))
    m = report.overall.metrics()
    per_sheet_wrong = sum(q.q % 3 == 0 for q in setup.questions)
    per_sheet_flagged = sum(q.q % 6 == 0 for q in setup.questions)
    n = len(samples)
    assert m["questions"] - round(m["question_accuracy"] * m["questions"]) == per_sheet_wrong * n
    assert m["silent_errors"] == (per_sheet_wrong - per_sheet_flagged) * n
    assert m["flag_rate"] == pytest.approx(per_sheet_flagged / len(setup.questions), abs=1e-6)
    assert m["team_accuracy"] == 1.0
    for entry in report.worst:
        assert all(q % 3 == 0 and q % 2 == 1 for q in entry["questions"])


def test_team_rules() -> None:
    setup = import_event_workbook(AP).setup
    assert setup is not None
    from app.harness.truth import SheetTruth

    def sample(team: list[list[int]]) -> Sample:
        truth = SheetTruth(sample_id="x", event_code="AP", sheet_version=1, layout_version=1,
                           marks={q.q: [] for q in setup.questions}, team_marks=team)  # fmt: skip
        return Sample("x", Path("x.jpg"), truth)

    def team_metrics(team: list[list[int]], read: SheetRead) -> tuple[float, int]:
        m = evaluate(setup, [sample(team)], lambda s: read).overall.metrics()
        return m["team_accuracy"], m["team_silent_errors"]

    assert team_metrics([[1], [2]], SheetRead(team_number=12)) == (1.0, 0)
    assert team_metrics([[1], [2]], SheetRead(team_number=13)) == (0.0, 1)  # silent
    assert team_metrics([[1], [2]], SheetRead(team_number=13, team_flagged=True)) == (0.0, 0)
    assert team_metrics([[1], []], SheetRead(team_flagged=True)) == (1.0, 0)  # flag, don't guess
    assert team_metrics([[1], [2, 5]], SheetRead(team_number=12)) == (0.0, 1)  # guessed


def test_report_files(dataset: tuple[Path, EventSetup, list[Sample]], tmp_path: Path) -> None:
    path, _, _ = dataset
    report = evaluate_dataset(path, READERS["blank"], "blank")
    report.write(tmp_path)
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["reader"] == "blank"
    assert set(data["by_condition"]) == {s.truth.condition for s in load_dataset(path)[1]}
    md = (tmp_path / "report.md").read_text()
    assert md.startswith("# Reader evaluation: `blank`")
    assert "| **All** |" in md and "## Bubble accuracy by how it was filled" in md
    assert "## Sheets with silent errors" in md


def test_score_error_uses_scoring_rules(dataset: tuple[Path, EventSetup, list[Sample]]) -> None:
    _, setup, samples = dataset
    report = evaluate(setup, samples[:1], blank_reader)
    true_total = score_sheet({q: set(v) for q, v in samples[0].truth.marks.items()}, setup).total
    assert report.overall.score_errors == [Decimal(true_total)]


def test_registry() -> None:
    assert set(READERS) == {"oracle", "blank", "detector"}


def test_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        load_dataset(tmp_path)
