# Phase 0 — Project scaffold (done)

**Status:** complete and merged into `main` (PR #1, 2026-11-21). CI green on `main`.

## Goal

A repository that every later phase can build on: tooling, database schema, validation shapes for event setup, and CI.

## What was delivered

- Git repo with `main` and the feature branch; `.gitignore` that blocks `.env`, keys and local databases.
- `backend/`: Python 3.12 FastAPI app managed with `uv`, settings from `.env` (`app/config.py`), `/health` route.
- Database (`app/db/models.py`, `migrations/versions/0001_initial_schema.py`): `graders`, `events`, `questions`, `teams`, `scans`, `free_response_scores`, `audit_log`.
  - DB-enforced rules: one counted scan per (event, team); one free-response total per (event, team); free-response ≥ 0 in 0.5 steps; options 2–9; unique question numbers per event; cascade delete from events.
  - Row-level security on all tables in Postgres so Supabase's public REST API exposes nothing.
- `app/schemas/event_setup.py`: Pydantic shapes for the Event tab, Questions tab and Teams CSV, with validation (letters within options, totals add up, no duplicate question numbers).
- CI (`.github/workflows/ci.yml`): ruff, mypy, migration drift check, pytest on SQLite and Postgres 16, gitleaks.
- Docs: `docs/STARTER_PROMPT.md`, `docs/DECISIONS.md` (Supabase over Firebase), README.

## Checks done

33 tests pass on SQLite and Postgres 16; app starts and `/health` responds; no secrets tracked.

## By the end of this phase (all met)

- [x] Repo pushed with `main` and `feat/project-scaffold`
- [x] All 7 tables created by one Alembic migration, tested on both databases
- [x] Event-setup validation shapes with tests
- [x] CI workflow committed
- [x] Database choice recorded with reasons

## Handoff to phase 1

Done: `feat/project-scaffold` merged into `main` via PR #1; CI passed on the PR and on `main`. Re-verified on 2026-11-21: 22 tests pass on SQLite and 33 on Postgres 16 (one RLS test runs on Postgres only). Phase 1 starts from `main` on branch `phase-01-event-import-and-scoring`.
