"""Fake sheet photos, a 3-page PDF and a fake camera video for the browser tests.

    uv run python scripts/e2e_assets.py ../frontend/e2e/.assets
    uv run python scripts/e2e_assets.py --pgm ../frontend/src/lib/__fixtures__/sheet_frame.pgm.gz
    uv run python scripts/e2e_assets.py --scoring ../frontend/src/lib/__fixtures__/scoring.json

All made from the example A&P event with fixed seeds, so every run gives the same files.
Teams match ``seed_e2e.py`` (1-12).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.harness.augment import photograph  # noqa: E402
from app.harness.samples import filled_page, sheet_photo, team_digits  # noqa: E402
from app.services.event_import import import_event_workbook  # noqa: E402

AP_FILE = BACKEND.parent / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"


def _setup():  # type: ignore[no-untyped-def]
    setup = import_event_workbook(AP_FILE).setup
    assert setup is not None
    return setup


def _key(setup) -> dict[int, list[str]]:  # type: ignore[no-untyped-def]
    return {q.q: list(q.correct) for q in setup.questions}


def _photo(setup, team: int, seed: int, size: tuple[int, int] = (1500, 2000)) -> bytes:  # type: ignore[no-untyped-def]
    digits = setup.event.team_number_digits
    return sheet_photo(setup, _key(setup), team_digits(team, digits), seed=seed, size=size)


def _y4m(jpeg: bytes, frames: int = 10) -> bytes:
    """A still video (YUV 4:2:0) for Chromium's --use-file-for-fake-video-capture."""
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV_I420).tobytes()
    head = f"YUV4MPEG2 W{w} H{h} F10:1 Ip A1:1 C420jpeg\n".encode()
    return head + b"".join(b"FRAME\n" + yuv for _ in range(frames))


def assets(out: Path) -> None:
    setup = _setup()
    out.mkdir(parents=True, exist_ok=True)
    (out / "sheet_team7.jpg").write_bytes(_photo(setup, 7, seed=7))
    (out / "sheet_team12.jpg").write_bytes(_photo(setup, 12, seed=12))
    pages = [Image.open(io.BytesIO(_photo(setup, t, seed=t))).convert("RGB") for t in (8, 9, 10)]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    (out / "three_pages.pdf").write_bytes(buf.getvalue())
    # Portrait 720x1280 "camera", like a phone held over the sheet.
    (out / "camera_team11.y4m").write_bytes(_y4m(_photo(setup, 11, seed=11, size=(720, 1280))))
    review_assets(setup, out)
    print(f"wrote e2e assets to {out}")


def _read(setup, jpeg: bytes):  # type: ignore[no-untyped-def]
    from app.services.detection import load_images, read_sheet

    img = load_images(jpeg, "x.jpg")[0]
    return read_sheet(img, lambda c, v: setup, fallback=setup, valid_teams=set(range(1, 13)))


def _find(setup, want, marks, team, styles=None) -> bytes:  # type: ignore[no-untyped-def]
    """First seed whose photo the real reader flags exactly as the test needs."""
    for seed in range(100, 160):
        jpeg = sheet_photo(setup, marks, team, seed=seed, styles=styles)
        if want(_read(setup, jpeg)):
            return jpeg
    raise SystemExit(f"no seed gave the wanted read for {team}")


def review_assets(setup, out: Path) -> None:  # type: ignore[no-untyped-def]
    """Sheets the review-screen tests need, each checked against the real reader."""
    from app.harness.truth import FillStyle, bubble_key

    key, d = _key(setup), setup.event.team_number_digits
    erased = "A" if key[5][0] != "A" else "B"  # a rubbed-out wrong answer next to the real one

    def only_q5(r) -> bool:  # type: ignore[no-untyped-def]
        flagged = [q for q, x in r.questions.items() if x.needs_review]
        return r.team_number == 4 and not r.team_flags and flagged == [5]

    def no_team(r) -> bool:  # type: ignore[no-untyped-def]
        flagged = [q for q, x in r.questions.items() if x.needs_review]
        return r.team_number is None and not flagged and r.readable

    def clean(n: int):  # type: ignore[no-untyped-def]
        return lambda r: r.team_number == n and not r.flagged_questions and r.readable

    sheets = {
        "review_erased_team4.jpg": _find(
            setup, only_q5, key, team_digits(4, d), {bubble_key(5, erased): FillStyle.erased}
        ),
        "review_noteam_a.jpg": _find(setup, no_team, key, [[] for _ in range(d)]),
        "review_noteam_b.jpg": _find(setup, no_team, {1: key[1]}, [[] for _ in range(d)]),
        "review_team99.jpg": _find(setup, clean(99), key, team_digits(99, d)),
        "review_dup_team6_a.jpg": _find(setup, clean(6), key, team_digits(6, d)),
        "review_dup_team6_b.jpg": _find(
            setup, clean(6), {q: v for q, v in key.items() if q != 1}, team_digits(6, d)
        ),
    }
    # Results tests: team 1 all right (60), team 3 only questions 1-10 right (10).
    sheets["results_team1.jpg"] = _find(setup, clean(1), key, team_digits(1, d))
    sheets["results_team3.jpg"] = _find(
        setup, clean(3), {q: key[q] for q in range(1, 11)}, team_digits(3, d)
    )
    for name, data in sheets.items():
        (out / name).write_bytes(data)


def pgm(path: Path) -> None:
    """A greyscale camera frame (tilted phone, gzipped PGM) for the browser marker test."""
    setup = _setup()
    rng = np.random.default_rng(3)
    page = filled_page(setup, {}, team_digits(5, setup.event.team_number_digits), rng=rng)
    photo = photograph(page, "perspective", rng, (540, 960), strength=0.6).decode()
    grey = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    h, w = grey.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = f"P5\n{w} {h}\n255\n".encode() + grey.tobytes()
    path.write_bytes(gzip.compress(raw, 9, mtime=0))
    print(f"wrote {path} ({w}x{h})")


def scoring_cases(path: Path) -> None:
    """Random answers scored by the server's rules, so the app's live score is checked
    against them. Uses the A&P key plus made-up partial-credit questions."""
    from app.schemas.event_setup import LETTERS, QuestionSetup
    from app.services.scoring import score_sheet

    ap = _setup()
    extra = [
        QuestionSetup(q=101, points="3", options=5, correct="A,C,E", scoring="partial",
                      penalty_per_wrong="0.5"),
        QuestionSetup(q=102, points="1", options=4, correct="B,C,D", scoring="partial"),
        QuestionSetup(q=103, points="2.5", options=6, correct="F", scoring="partial",
                      penalty_per_wrong="0.25"),
    ]  # fmt: skip
    questions_setup = [*ap.questions, *extra]
    rng = random.Random(42)
    cases = []
    for _ in range(40):
        marks: dict[int, list[str]] = {}
        for q in questions_setup:
            r = rng.random()
            if r < 0.15:
                continue
            letters = LETTERS[: q.options]
            k = 1 if r < 0.7 else rng.randint(1, min(3, q.options))
            marks[q.q] = sorted(rng.sample(letters, k)) if r >= 0.4 else list(q.correct)
        cases.append({"marks": marks, "total": str(score_sheet(marks, questions_setup).total)})
    questions = [
        {"q": q.q, "points": str(q.points), "correct": list(q.correct),
         "scoring": q.scoring.value, "penalty_per_wrong": str(q.penalty_per_wrong)}
        for q in questions_setup
    ]  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"questions": questions, "cases": cases}) + "\n")
    print(f"wrote {path} ({len(cases)} cases)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out", nargs="?", type=Path)
    p.add_argument("--pgm", type=Path)
    p.add_argument("--scoring", type=Path)
    a = p.parse_args()
    if not (a.out or a.pgm or a.scoring):
        p.error("give an output folder, --pgm FILE and/or --scoring FILE")
    if a.out:
        assets(a.out)
    if a.pgm:
        pgm(a.pgm)
    if a.scoring:
        scoring_cases(a.scoring)
