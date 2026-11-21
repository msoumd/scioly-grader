# Decisions

Short record of choices made while building. Newest first.

## 2026-11-21 — Database: Supabase (Postgres), accessed through SQLAlchemy

**Choice:** Supabase for production (hosted Postgres + Storage for scan images). SQLite for local dev and tests.

**Why not Firebase:** The data is relational: events → questions, teams, scans → per-question marks, free-response scores, and an audit log. The results table is a join of scans and free-response scores per (event, team), with uniqueness rules (one counting scan per team per event). That is natural in SQL and awkward in Firestore (no joins, no unique constraints, denormalised writes). The spec also already says "SQLite for dev, Postgres in production", which Supabase is.

**How we use it:** The FastAPI backend talks to the database only through SQLAlchemy and Alembic migrations, with `DATABASE_URL` choosing SQLite or Supabase Postgres. No Supabase client SDK in the backend, so the app is not locked in and tests run without network. Scan images go through a small storage interface: local folder in dev, Supabase Storage bucket in production (added in build step 4/7). Grader login is the app's own shared-PIN + grader name (spec), not Supabase Auth, to keep the iPhone flow to one screen.

## 2026-11-21 — Repo layout

- `backend/` — Python 3.12+ FastAPI app (`app/`), Alembic migrations, pytest tests. Managed with `uv`.
- `frontend/` — PWA, created at build step 5.
- `event_setups/` — supervisor spreadsheets (A&P is the first real event).
- `docs/` — spec (`STARTER_PROMPT.md`) and this file.
