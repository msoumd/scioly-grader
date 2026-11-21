# Phase 2 — Sheet layout and PDF generator

**Starter-prompt step:** 2, first half (scantron PDF generator)
**Branch:** `phase-02-sheet-pdf`
**Depends on:** phase 1 merged (imported events)
**Status:** built on branch `phase-02-sheet-pdf`, awaiting review.

## Goal

For any imported event, produce a printable one-page bubble sheet whose every mark position is known exactly. The same layout code is later used by the detector, so the printed page and the reader can never disagree.

## Key design: one layout module, two users

`app/services/layout.py` computes, from an `EventSetup`, a `SheetLayout` in **page coordinates (points, 1/72 in, origin top-left)**:
- the four corner marker squares and their IDs,
- the QR code box,
- the team-number grid (one column per digit, rows 0–9),
- every question's label position and every bubble centre and radius,
- the team-name box (handwritten, not read).

The PDF renderer (this phase) draws from `SheetLayout`; the detector (phase 4) reads from the same `SheetLayout`. No coordinates are hard-coded anywhere else.

## Scope

### In
- Layout engine, PDF renderer, QR payload, CLI and API-free generation.

### Out
- Reading sheets (phase 4), fake fills (phase 3), web download button (phase 5/6).

## Tasks

1. **Libraries:** `reportlab` (PDF), `segno` (QR), `opencv-contrib-python-headless` (ArUco marker images; also needed in phase 4). Record in `DECISIONS.md`.
2. **Page and markers**
   - US Letter, 0.5 in margins, black and white only, no grey fills (copier-safe).
   - Four ArUco markers from `DICT_4X4_50`, IDs 0 (top-left), 1 (top-right), 2 (bottom-right), 3 (bottom-left), 0.6 in square, with a white quiet zone. Distinct IDs let the reader know the page orientation even if the photo is upside down.
3. **Header**
   - Event name, tournament, date, `sheet_version`, printed in text for humans.
   - QR code (≥ 0.9 in, error correction M) encoding compact JSON `{"e":"AP","v":1}`.
   - Team-name box (handwritten).
   - Team-number grid: `team_number_digits` columns × digits 0–9, with write-in boxes above each column.
4. **Question block**
   - Bubbles labelled A, B, C… inside each circle (so students can see which is which), question number to the left.
   - Each row's length follows that question's `options`.
   - Packing: fill columns top to bottom; column width = widest row in the column. Default pitch 0.25 in, bubble diameter 0.18 in; shrink pitch down to a minimum of 0.21 in if needed to fit.
   - Capacity requirement: **at least 100 questions with up to 5 options** on one page. If an event cannot fit (e.g. 100 questions × 9 options), raise a clear error naming how many fit, rather than producing a cramped sheet. Note the limit in the import report.
   - Light timing ticks are not needed; the four markers plus the known layout are enough.
5. **Determinism:** same `EventSetup` ⇒ byte-identical layout numbers (PDF bytes may differ in metadata; set fixed creation date so they don't). Layout carries a `layout_version` so future layout changes don't break reading old sheets.
6. **CLI:** `uv run python -m app.cli make-sheet AP --out data/generated/AP_v1.pdf` (from DB) or `--from-xlsx path.xlsx` (no DB needed).
7. **Render-to-image helper** `render_sheet_png(layout, dpi=200)` using `pypdfium2` (or draw directly with OpenCV from the layout) — phase 3 uses it to make fake sheets.

## Tests

- Layout geometry: no two bubbles overlap; every element is inside the margins and outside the marker quiet zones; label positions don't collide with bubbles.
- Capacity: 100 × 5-option fits; 54-question A&P fits on one page with room to spare; 100 × 9-option either fits at min pitch or raises the documented error.
- Determinism: generating twice gives identical `SheetLayout` (compare JSON dumps); golden-file snapshot of the A&P layout JSON checked into `tests/golden/`.
- QR round-trip: render page to PNG, decode QR with OpenCV, get back `{"e":"AP","v":1}`.
- Markers: render to PNG, `cv2.aruco` finds exactly IDs 0–3 at the expected positions (± 2 px at 200 dpi).
- Team-number grid has `team_number_digits` columns.

## CI changes

- Install the new libraries; upload the generated A&P PDF as a CI artifact so it can be eyeballed from any PR.

## By the end of this phase

- [x] `make-sheet` produces a one-page Letter PDF for each example event, in the style of the current A&P answer sheet (bubbles in columns, team grid, name box) plus markers and QR
- [x] Layout is defined once in `layout.py` and covered by geometry, determinism and golden tests
- [x] Rendered PNG round-trips the QR and all four markers in tests
- [x] Capacity rule enforced with a clear error
- [ ] PDF attached to the summary for Yuvan
- [ ] CI green

## Review checkpoint for Yuvan

- Print the A&P sheet on a normal printer and on the copier you'll use at the tournament. Check bubbles are easy to fill and nothing is cut off.
- Optional: fill one by hand and photograph it; keep it for phase 4 as the first real sample.

## Risks

- Printers scaling to "fit page" shift everything. Markers make the reader robust to scale, but the summary should tell supervisors to print at 100%.
- Copiers darkening backgrounds: keep the page pure black and white.
