# Phase 3 — Fake-sheet test harness

**Starter-prompt step:** 2, second half (fake-sheet test harness)
**Branch:** `phase-03-fake-sheets`
**Depends on:** phase 2 merged (layout + render-to-image)
**Status:** built on branch `phase-03-fake-sheets`, awaiting review.

## Goal

A script that turns any event setup into many fake filled-in sheets with **known** answers, under realistic photo conditions. This is the yardstick phase 4 is measured against, so it is built and trusted before detection exists.

## Scope

### In
- Synthetic "student" fills, image augmentations, a labelled dataset on disk, and the scoring/report skeleton that phase 4 plugs into.

### Out
- The detector itself (phase 4).

## Tasks

1. **Ground truth model** — `app/harness/truth.py`: `SheetTruth { event_code, sheet_version, team_number (or partial), marks: {q: set[str]}, fill_styles: {(q, letter): style} }`. Saved as JSON beside each image.
2. **Answer generator** — given a setup and a seed, produce a realistic answer pattern: mostly single answers, some multi-select on multi-select questions, ~5% blanks, ~3% double marks on single-answer questions, sometimes all correct, sometimes random.
3. **Mark painter** — draws fills onto the clean rendered page (from phase 2) at the layout's bubble positions:
   - `solid` (dark pencil), `light` (light pencil, 40–60% coverage), `partial` (fill only part of the circle), `check` / `x` (non-standard marks), `erased` (faint smudge that should read as blank), `stray` (small mark outside a bubble).
   - Team-number digits bubbled the same way, plus cases with a missing digit or two digits bubbled in one column.
   - Pencil texture: noisy grey strokes, not perfect black discs.
4. **Augmentations** — `app/harness/augment.py`, each with strength levels and a fixed seed:
   - glare from overhead lights (added after review of the plan),
   - rotation (±5°, ±15°, 90°, 180°), perspective tilt (up to ~25°), scale (phone 1–3 ft away), blur (focus, motion), uneven lighting and shadows (a hand/phone shadow band), low light + noise, JPEG compression, colour cast (warm indoor light), paper curl (mild warp), crop with one corner near the edge, background clutter (desk texture around the page).
   - Combined "realistic phone" preset that stacks a random mild subset.
5. **Dataset builder CLI** — `uv run python -m app.harness build --event AP --n 200 --conditions all --out data/harness/AP/` writes `NNNN.jpg` + `NNNN.json` and a `manifest.json` (conditions, seeds, counts). Fully reproducible from seeds.
6. **Evaluator skeleton** — `app/harness/evaluate.py`: takes a `read_sheet(image) -> SheetRead` function (stub for now), runs it on a dataset, compares to truth, and writes `report.md` + `report.json` with metrics **per condition**:
   - bubble accuracy, question accuracy, team-number accuracy,
   - **silent error rate**: wrong and not flagged (the metric that matters most),
   - flag rate: share of questions sent to human review,
   - score error: |detected score − true score| distribution.
   A trivial "perfect oracle" reader (returns the truth) must score 100%, and a "always blank" reader must score as expected; both are tests.
7. **Real samples folder** — `backend/data/real_samples/` (git-ignored for photos with student info; commit only blank or staff-filled samples) with a README on how to add hand-filled phone photos and label them, so the evaluator runs on real photos too.

## Tests

- Painter puts marks exactly where the layout says (check pixel darkness inside vs outside bubbles on the clean page).
- Each augmentation is deterministic for a seed, and keeps the image size within bounds.
- Truth JSON round-trips.
- Evaluator: oracle → 100%; always-blank → known numbers; a deliberately wrong reader → silent errors counted correctly.
- Small dataset (10 sheets) builds in CI in under 30 s.

## CI changes

- Build a 10-sheet dataset and run the evaluator with the oracle as a smoke test. Upload a few sample images as an artifact.

## By the end of this phase

- [x] One command builds a reproducible labelled dataset for any event, across all listed conditions
- [x] Sample images look like real phone photos of a filled sheet (attach a contact sheet image to the summary)
- [x] Evaluator produces the per-condition report and is proven correct with oracle and broken readers
- [x] Instructions exist for adding real phone photos as extra test data
- [x] CI green

## Review checkpoint for Yuvan

- Look at the contact sheet: do the fake photos look as bad as real ones from graders' phones? Suggest missing conditions (e.g. glare from overhead lights).
- If possible, take 10 real photos of hand-filled sheets (from phase 2's printout) for phase 4.

## Risks

- Fakes that are too clean give a falsely good accuracy number. Real-photo samples are the check on that; phase 4 reports real and fake separately.
