# Phase 4 — Detection and accuracy report

**Starter-prompt step:** 3 (detection and scoring, with accuracy report)
**Branch:** `phase-04-detection`
**Depends on:** phase 3 merged (harness and evaluator)
**Status:** built on branch `phase-04-detection`; accuracy report in `docs/reports/phase-04-accuracy-summary.md`. **Approved by Yuvan on 2026-11-21** (keep the cautious `multiple_marks` rule).

## Goal

Read a photo or scan of a bubble sheet: find the page, identify the event, read the team number and every bubble, score it, and flag anything uncertain. Prove it with the phase 3 accuracy report. **No UI is built until Yuvan approves the accuracy numbers** (starter-prompt rule).

## Scope

### In
- Server-side reading pipeline (OpenCV, no AI/ML), PDF page splitting, flags, accuracy report on fake and real images.

### Out
- HTTP routes (phase 5), client-side camera guidance (phase 6).

## Pipeline — `app/services/detection/`

1. **Load** — JPEG/PNG/HEIC (iPhone; use `pillow-heif`) and multi-page PDFs (render each page at 200 dpi with `pypdfium2`). Apply EXIF orientation. Downscale huge photos to ~2500 px on the long edge.
2. **Find markers** — `cv2.aruco.ArucoDetector` with `DICT_4X4_50`; tune refinement for small/blurry markers. Need IDs 0–3. If 3 are found, estimate the 4th from the layout geometry and flag `marker_missing`. If fewer, fail with `page_not_found` (tell the grader to retake).
3. **Warp** — homography from marker centres to their layout positions; warp to a canonical page image at a fixed resolution (e.g. 200 dpi = 1700 × 2200 px). Marker IDs fix orientation, so upside-down photos work.
4. **Read QR** — `cv2.QRCodeDetector` on the known QR region (try the full page as fallback). Gives `event_code` + `sheet_version`. Missing/unknown → `event_unknown` flag; the grader can pick the event manually.
5. **Look up layout** — rebuild `SheetLayout` from the stored event setup + `layout_version`, so bubble positions match the printed sheet exactly.
6. **Measure bubbles** — for each bubble: crop a small window, local alignment (search ±3 px for best fit to compensate for slight warp/paper curl), then fill ratio = share of dark pixels inside the inner circle after adaptive (local) thresholding, plus mean darkness. Normalise against the page's own blank-bubble level (median of the darkest-free bubbles) so lighting and pencil darkness don't matter.
7. **Decide marks per question**
   - Marked: fill clearly above the page's blank level and above an absolute floor.
   - Erasure handling: a faint fill much lighter than the other marks on the page counts as blank, but if it is close to the threshold → `ambiguous`.
   - Single-answer question (correct set size 1) with two marks: treat as marked both (scores 0 under `exact`), and flag `multiple_marks` only if one is much darker (possible erasure).
   - Every question gets a confidence; below threshold → `ambiguous`.
   - No marks → `blank` flag (informational, not an error).
8. **Team number** — same per digit column: exactly one mark → digit; none → `team_digit_missing`; two → `team_digit_ambiguous`. Resulting number not in the Teams list → `team_unknown`. Already has a counted scan for this event → `duplicate_team` (checked in phase 5 where the DB is available; return the info needed).
9. **Score** — phase 1's `score_sheet` on the detected marks.
10. **Output** — `SheetRead { event_code, sheet_version, team_number, marks, per_question {fill values, confidence, flags}, page_flags, mcq_score, warped_image, bubble_crops }`. Crops are what the review screen (phase 7) shows.
11. **Thresholds in one config** (`detection/config.py`) with the values chosen by the evaluation below, documented in `DECISIONS.md`.

## Accuracy work

- Build a large dataset with phase 3 (e.g. 300 sheets per example event in `event_setups/` across all conditions).
- Run the evaluator; iterate on thresholds and alignment until targets are met.
- Run on the real phone photos from phases 2–3, reported separately.
- **Targets (proposed, Yuvan to confirm):**
  - Silent error rate (wrong and not flagged) **≤ 0.1% of questions** on realistic conditions, **0** on the team number.
  - Question accuracy after flags ≥ 99.5% on mild conditions.
  - Flag rate ≤ 3% of questions on mild conditions (so review stays fast).
  - Hard conditions (heavy shadow, 25° tilt, motion blur) may flag more but must stay at the same silent-error target.
  - Reading one photo in < 2 s on the deploy machine size.

## Tests

- Unit: marker finding with 3 of 4 markers, orientation (0/90/180/270), QR missing, fill-ratio math on synthetic discs, decision rules (single vs multi, erasure, ambiguous), team-number rules.
- Integration: generate → fill → augment → read → score equals truth for a fixed seed set (fast subset in CI).
- Multi-page PDF: 3 sheets in one PDF → 3 reads.
- Regression: check in the `report.json` from the approved run; CI fails if silent error rate on the CI subset gets worse.

## CI changes

- Run the detection regression subset (~50 sheets) on every PR; upload `report.md` as an artifact.

## By the end of this phase

- [x] `uv run python -m app.cli read-sheet photo.jpg` prints event, team, marks, flags and score
- [x] Accuracy report per condition for fake photos (real photos deferred to end-to-end testing, by Yuvan's decision)
- [x] Targets met, or a clear explanation of which conditions fall short and what the grader would see
- [x] Thresholds and their reasons recorded in `DECISIONS.md`
- [x] CI regression gate in place
- [x] **Yuvan has approved the accuracy numbers in writing** before phase 5 starts (2026-11-21, PR #7)

## Review checkpoint for Yuvan

- Read the per-condition table. Decide whether the flag rate and silent-error rate are acceptable for the tournament.
- Look at 10 flagged examples (crops included) to judge whether flags are sensible.

## Risks

- Real pencil on cheap copier paper can be lighter than the fakes; the page-relative normalisation is the main defence, real samples are the proof.
- iPhone HEIC uploads; covered by `pillow-heif`.
- Glare on glossy paper is not fully solvable; it should become `ambiguous`, never a silent error.
