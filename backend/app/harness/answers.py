"""Realistic answer patterns for a fake student team, from a seed."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.harness.truth import FillStyle, bubble_key, team_key
from app.schemas.event_setup import LETTERS, EventSetup

BLANK_RATE = 0.05
DOUBLE_MARK_RATE = 0.03  # on single-answer questions
ERASE_RATE = 0.05  # a question with a leftover erased bubble
STYLE_WEIGHTS = {
    FillStyle.solid: 0.72,
    FillStyle.light: 0.10,
    FillStyle.partial: 0.10,
    FillStyle.check: 0.04,
    FillStyle.x: 0.04,
}


@dataclass(frozen=True)
class FakeAnswers:
    profile: str  # "perfect" | "random" | "typical"
    marks: dict[int, list[str]]
    team_marks: list[list[int]]
    fill_styles: dict[str, FillStyle]
    strays: int


def _style(rng: np.random.Generator) -> FillStyle:
    styles = list(STYLE_WEIGHTS)
    weights = np.array(list(STYLE_WEIGHTS.values()))
    return styles[int(rng.choice(len(styles), p=weights / weights.sum()))]


def _pick(rng: np.random.Generator, pool: list[str], k: int) -> list[str]:
    return sorted(str(x) for x in rng.choice(pool, size=min(k, len(pool)), replace=False))


def generate_answers(setup: EventSetup, rng: np.random.Generator) -> FakeAnswers:
    roll = rng.random()
    profile = "perfect" if roll < 0.1 else "random" if roll < 0.2 else "typical"
    accuracy = {"perfect": 1.0, "random": 0.0}.get(profile, float(rng.uniform(0.4, 0.95)))

    marks: dict[int, list[str]] = {}
    styles: dict[str, FillStyle] = {}
    for q in setup.questions:
        letters = list(LETTERS[: q.options])
        key = list(q.correct)
        if profile != "perfect" and rng.random() < BLANK_RATE:
            chosen: list[str] = []
        elif rng.random() < accuracy:
            chosen = sorted(key)
        elif len(key) > 1:
            # Multi-select, got it wrong: drop one, add one, or pick a random set.
            move = rng.integers(3)
            if move == 0:
                chosen = _pick(rng, key, len(key) - 1)
            elif move == 1 and len(key) < len(letters):
                extra = _pick(rng, [x for x in letters if x not in key], 1)
                chosen = sorted(key + extra)
            else:
                chosen = _pick(rng, letters, int(rng.integers(1, len(letters) + 1)))
        else:
            wrong = [x for x in letters if x not in key]
            chosen = _pick(rng, wrong or letters, 1)
        if len(key) == 1 and chosen and rng.random() < DOUBLE_MARK_RATE:
            others = [x for x in letters if x not in chosen]
            chosen = sorted(chosen + _pick(rng, others, 1))
        marks[q.q] = chosen
        for letter in chosen:
            styles[bubble_key(q.q, letter)] = _style(rng)
        unmarked = [x for x in letters if x not in chosen]
        if unmarked and rng.random() < ERASE_RATE:
            styles[bubble_key(q.q, _pick(rng, unmarked, 1)[0])] = FillStyle.erased

    digits = setup.event.team_number_digits
    number = int(rng.integers(1, 10**digits))
    team: list[list[int]] = [[int(d)] for d in str(number).zfill(digits)]
    case = rng.random()
    if case < 0.05:
        team[int(rng.integers(digits))] = []  # forgot to bubble one digit
    elif case < 0.10:
        col = int(rng.integers(digits))  # two digits bubbled in one column
        first = team[col][0]
        team[col] = sorted([first, (first + int(rng.integers(1, 10))) % 10])
    for c, col_digits in enumerate(team):
        for d in col_digits:
            styles[team_key(c, d)] = FillStyle.solid if rng.random() < 0.9 else FillStyle.light

    return FakeAnswers(
        profile=profile,
        marks=marks,
        team_marks=team,
        fill_styles=styles,
        strays=int(rng.choice([0, 0, 0, 1, 2, 3])),
    )
