# Build phases

The project is built in sequential phases. Each phase is one working session that ends with a review by Yuvan before the next one starts. Do them in order: each one depends on what the previous one delivered.

| # | Phase | Starter-prompt step | Ends with |
|---|-------|---------------------|-----------|
| 0 | [Project scaffold](phase-00-project-scaffold.md) | — | Repo, schema, CI (**done**) |
| 1 | [Event import and scoring](phase-01-event-import-and-scoring.md) | 1 | A&P spreadsheet imports; scoring function fully tested |
| 2 | [Sheet layout and PDF generator](phase-02-sheet-layout-and-pdf.md) | 2a | Printable bubble page for any event |
| 3 | [Fake-sheet test harness](phase-03-fake-sheet-harness.md) | 2b | Thousands of realistic fake filled sheets with known answers |
| 4 | [Detection and accuracy report](phase-04-detection-and-accuracy.md) | 3 | Measured accuracy per condition — **Yuvan must approve before any UI** |
| 5 | [API, auth and storage](phase-05-api-auth-storage.md) | 4 | Full backend API over HTTP, images stored, graders logged in |
| 6 | [Frontend shell and capture](phase-06-frontend-and-capture.md) | 5a | iPhone PWA that captures or uploads a sheet |
| 7 | [Review screen](phase-07-review-screen.md) | 5b | Grader fixes flags and confirms a scan |
| 8 | [Free response, results, export](phase-08-free-response-results-export.md) | 6 | Results table with ranks and CSV export |
| 9 | [Deploy](phase-09-deploy.md) | 7 | App live over HTTPS on Supabase + Render |
| 10 | [Tournament readiness](phase-10-tournament-readiness.md) | — | Dress rehearsal with real sheets and phones, runbook |

## Rules for every phase

These apply to all phases and are not repeated in each file.

1. **Branch:** start from up-to-date `main` (after the previous phase's PR is merged). Name it `phase-NN-short-name`.
2. **Commit small and often.** One logical change per commit, so any step can be rolled back.
3. **Never commit secrets.** `.env` stays git-ignored; real values go in `.env` locally and in the host's secret settings in production. CI runs gitleaks.
4. **Verify before every commit:** `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest` in `backend/` (and the frontend equivalents from phase 6 on). Run Postgres tests too when the phase touches the database.
5. **Tests ship with the code.** Unit tests for logic, integration tests for API routes, Playwright end-to-end tests for every user flow from phase 6 on. CI must be green before a PR is opened.
6. **Schema changes only through Alembic migrations**, reviewed before commit. CI fails on drift.
7. **Update docs as you go:** record any non-obvious choice in `docs/DECISIONS.md`, and keep the README run instructions true.
8. **End of phase:** push the branch, open a PR when Yuvan asks, write a short summary of what was built, what was checked, and any open questions. Stop and wait for review.
9. **Plain-language summaries.** Yuvan is not a coder: explain decisions briefly and in plain words.

## Open questions carried forward

| Question | Blocks | Owner |
|----------|--------|-------|
| A&P total: 200 (student sheet) or 210 (key)? | Phase 1 sign-off on A&P | Yuvan |
| What are scantron rows 55–66 on the A&P key? | Phase 1 sign-off on A&P | Yuvan |
| Fill in the Forensics template as a second test event? | Phase 1 (nice to have), phase 4 | Yuvan |
| Hosting cost approval (Render + Supabase paid tier, if needed) | Phase 9 | Yuvan |
