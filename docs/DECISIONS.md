# Decisions

Short record of choices made while building. Newest first.

## 2026-11-21 — Answer-sheet layout and libraries (phase 2)

**One layout, two users.** `app/services/layout.py` computes every position on the page (markers, QR, team grid, each bubble) from the event setup. The PDF renderer only draws that, and the reader (phase 4) will only read that, so the printed page and the reader cannot disagree. Positions are in PDF points from the top-left corner, rounded to 0.01 pt, and golden files catch any accidental change. `LAYOUT_VERSION` must go up whenever positions change.

**Look.** It follows the ZipGrade-style sheet supervisors already use: lettered bubbles in columns, a team-name box at the top left, a team-number grid at the bottom right (one column per digit, write-in boxes above, digits 0–9). Added on top are four corner markers and a QR code. Columns are balanced so they come out even.

**Fitting the page.** Bubble spacing starts at 0.25 in and shrinks in 0.01 in steps down to 0.21 in only if needed. 100 five-choice questions fit at full spacing. If an event cannot fit even at 0.21 in, the import report says so and names how many would fit; the app never prints a cramped sheet.

**Machine-readable parts.**
- Four ArUco markers (`DICT_4X4_50`, IDs 0–3 clockwise from top-left, 0.6 in) let the reader find the page and its orientation from any phone photo, even upside down.
- The QR code holds `{"e":"<event_id>","v":<sheet_version>}`, so a scan knows which event and key to use. The error correction is at least M; the library raises it to Q when that fits at the same size.

**Copier-safe.** Pure black on white, no grey. Bubble letters are printed in thin black, which the reader will account for. The header asks for printing at 100% (actual size).

**Libraries.**
- `reportlab` draws the PDF; it was chosen because it can produce byte-identical files, so the same event always gives the same PDF.
- `segno` makes the QR code (pure Python).
- `opencv-contrib-python-headless` makes the ArUco markers and will read sheets in phase 4.
- `pypdfium2` turns the PDF into an image for tests and the phase 3 fake-sheet generator.

## 2026-11-21 — The app is event-agnostic

Nothing is built or tuned for a specific test. A&P was only the first example. Each event's numbers (question count, numbering, options per question, points, total, free-response share) come from its setup spreadsheet. `event_setups/` holds examples; CI imports every one of them. The Forensics example copies a real sheet's *structure* (only 11 bubble questions, numbered with gaps, 3–5 options, half points, 286/300 free response), but its correct letters are made up because this repo is public.

## 2026-11-21 — Scoring rules (phase 1)

**Exact questions:** full points only if the marked bubbles are exactly the key, otherwise 0. Marking an extra bubble on a single-answer question gets 0.

**Partial questions:** `points × (correct picks ÷ number of correct answers) − penalty_per_wrong × wrong picks`, never below 0 and never above the question's points.
- *Over-marking:* with `penalty_per_wrong` = 0, extra wrong bubbles cost nothing. Marking every bubble then earns full points. This is what the template's formula says, so it is kept as written. Supervisors who use `partial` should set a penalty if over-marking should be punished.
- Worked example: key A,C worth 2 points, penalty 0.25. Marked A → 2 × ½ = **1**. Marked A,B → 1 − 0.25 = **0.75**. Marked A,B,C → 2 − 0.25 = **1.75**. Marked B,D → 0 − 0.5, floored to **0**.

**Rounding:** all arithmetic uses exact decimals. Each question's points are kept exact (⅓ stays ⅓), and only the sheet total is rounded, to 2 decimals, half-up (0.125 → 0.13). Three ⅓-point answers total 1.00, not 0.99.

## 2026-11-21 — Re-importing an event setup (phase 1)

- New `event_id` → saved.
- Same `event_id`, **no scans yet** → the event's settings and questions are replaced. Fixing mistakes while setting up is easy.
- Same `event_id`, **scans exist** → refused unless `sheet_version` on the Event tab is higher than the saved one. This stops the answer key silently changing under scores that already exist. With a higher version, the new key is saved and old scans keep their old version number; re-scoring them is a phase 5 feature.
- The import commands only check the file unless `--save` is given.
- The spreadsheet's formula rows (`mcq_points_total (auto)`, `check`) are ignored. The total is recomputed from the question rows, because formula values are often missing when a file is saved by tools other than Excel.

## 2026-11-21 — Database: Supabase (Postgres), accessed through SQLAlchemy

**Choice:** Supabase for production (hosted Postgres + Storage for scan images). SQLite for local dev and tests.

**Why not Firebase:** The data is relational: events → questions, teams, scans → per-question marks, free-response scores, and an audit log. The results table is a join of scans and free-response scores per (event, team), with uniqueness rules (one counting scan per team per event). That is natural in SQL and awkward in Firestore (no joins, no unique constraints, denormalised writes). The spec also already says "SQLite for dev, Postgres in production", which Supabase is.

**How we use it:** The FastAPI backend talks to the database only through SQLAlchemy and Alembic migrations, with `DATABASE_URL` choosing SQLite or Supabase Postgres. No Supabase client SDK in the backend, so the app is not locked in and tests run without network. Scan images go through a small storage interface: local folder in dev, Supabase Storage bucket in production (added in build step 4/7). Grader login is the app's own shared-PIN + grader name (spec), not Supabase Auth, to keep the iPhone flow to one screen.

## 2026-11-21 — Repo layout

- `backend/` — Python 3.12+ FastAPI app (`app/`), Alembic migrations, pytest tests. Managed with `uv`.
- `frontend/` — PWA, created at build step 5.
- `event_setups/` — supervisor spreadsheets (A&P is the first real event).
- `docs/` — spec (`STARTER_PROMPT.md`) and this file.
