"""Fake answers look like a real team's, and truth files round-trip."""

from collections import Counter
from pathlib import Path

import numpy as np

from app.harness.answers import generate_answers
from app.harness.truth import MARKING_STYLES, FillStyle, SheetTruth, bubble_key
from app.schemas.event_setup import LETTERS
from app.services.event_import import import_event_workbook

AP = Path(__file__).resolve().parents[2] / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"
SETUP = import_event_workbook(AP).setup
assert SETUP is not None


def test_same_seed_same_answers() -> None:
    a = generate_answers(SETUP, np.random.default_rng(7))
    b = generate_answers(SETUP, np.random.default_rng(7))
    assert a == b
    assert a != generate_answers(SETUP, np.random.default_rng(8))


def test_answers_are_valid_letters_and_styled() -> None:
    for seed in range(50):
        ans = generate_answers(SETUP, np.random.default_rng(seed))
        assert set(ans.marks) == {q.q for q in SETUP.questions}
        for q in SETUP.questions:
            chosen = ans.marks[q.q]
            assert chosen == sorted(set(chosen))
            assert set(chosen) <= set(LETTERS[: q.options])
            for letter in chosen:
                assert ans.fill_styles[bubble_key(q.q, letter)] in MARKING_STYLES
        erased = [k for k, s in ans.fill_styles.items() if s is FillStyle.erased]
        for key in erased:
            q, letter = key.split(":")
            assert letter not in ans.marks[int(q)], "erased bubble must not be an answer"
        assert len(ans.team_marks) == SETUP.event.team_number_digits


def test_population_rates_are_realistic() -> None:
    blanks = doubles = total_single = 0
    profiles: Counter[str] = Counter()
    team_cases: Counter[str] = Counter()
    for seed in range(400):
        ans = generate_answers(SETUP, np.random.default_rng(seed))
        profiles[ans.profile] += 1
        sizes = [len(c) for c in ans.team_marks]
        team_cases["normal" if sizes == [1] * len(sizes) else "odd"] += 1
        for q in SETUP.questions:
            chosen = ans.marks[q.q]
            blanks += not chosen
            if len(q.correct) == 1:
                total_single += 1
                doubles += len(chosen) > 1
    n_q = 400 * len(SETUP.questions)
    assert 0.02 < blanks / n_q < 0.08
    assert 0.01 < doubles / total_single < 0.06
    assert 20 < profiles["perfect"] < 70 and 20 < profiles["random"] < 70
    assert 15 < team_cases["odd"] < 70


def test_truth_round_trip(tmp_path: Path) -> None:
    ans = generate_answers(SETUP, np.random.default_rng(3))
    truth = SheetTruth(
        sample_id="0001",
        event_code="AP",
        sheet_version=1,
        layout_version=1,
        condition="clean",
        seed=3,
        marks=ans.marks,
        team_marks=ans.team_marks,
        fill_styles=ans.fill_styles,
        strays=ans.strays,
        page_corners=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)],
        augment={"angle": 1.5, "jpeg_quality": 90},
    )
    path = tmp_path / "0001.json"
    truth.save(path)
    assert SheetTruth.load(path) == truth


def test_team_number_only_when_unambiguous() -> None:
    def truth(team: list[list[int]]) -> SheetTruth:
        return SheetTruth(sample_id="x", event_code="E", sheet_version=1, layout_version=1,
                          marks={}, team_marks=team)  # fmt: skip

    assert truth([[0], [7]]).team_number == 7
    assert truth([[1], [2], [3]]).team_number == 123
    assert truth([[1], []]).team_number is None
    assert truth([[1], [2, 5]]).team_number is None
