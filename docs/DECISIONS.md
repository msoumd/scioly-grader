# Decisions

Short record of choices made while building. Newest first.

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
