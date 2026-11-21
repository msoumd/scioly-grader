# Phase 5 — API, auth and storage

**Starter-prompt step:** 4 (API and database)
**Branch:** `phase-05-api`
**Depends on:** phase 4 merged **and accuracy approved by Yuvan**

## Goal

Everything the app does, available over HTTP and saved in the database: graders log in, events and teams are imported, sheets are uploaded and read, scans are reviewed and confirmed, free-response totals are entered, results and CSV come out, and every edit is audited. The frontend phases only build screens on top of this.

## Scope

### In
- Grader login, all JSON routes, image storage, background reading, audit log, duplicate handling, OpenAPI docs.

### Out
- Screens (phases 6–8), hosting (phase 9).

## Tasks

1. **Auth** — `app/api/auth.py`
   - `POST /api/login {pin, grader_name}`: PIN compared with `TOURNAMENT_PIN` using a constant-time compare; creates the grader row if new; returns an HTTP-only, Secure, SameSite=Lax signed session cookie (`itsdangerous`, secret `SESSION_SECRET` from env), valid for the tournament day.
   - Optional `ADMIN_PIN` for supervisor-only actions (import events, delete scans, resolve duplicates). Two roles: `grader`, `admin`.
   - Rate-limit login attempts per IP (simple in-memory limiter) to stop PIN guessing.
   - `GET /api/me`, `POST /api/logout`.
2. **Storage** — `app/services/storage.py`, an interface with two implementations:
   - `LocalStorage` (dev/tests): files under `UPLOAD_DIR`.
   - `SupabaseStorage` (prod): private bucket `scans`, uploads via the Storage REST API with the service-role key (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` in env only), signed URLs (short expiry) for viewing.
   - Store: original upload (always kept, never modified), warped page, bubble crops for flagged questions.
3. **Routes** (all under `/api`, Pydantic request/response models, errors as `{detail, code}`)
   - Events: `POST /events/import` (xlsx upload → import report; `?dry_run=true` for a preview), `GET /events`, `GET /events/{code}`, `GET /events/{code}/sheet.pdf`.
   - Teams: `POST /teams/import` (CSV), `GET /teams`.
   - Scans: `POST /scans` (image or PDF; returns scan ids immediately, status `processing`), `GET /scans/{id}` (marks, flags, crop URLs, score), `GET /events/{code}/scans?status=needs_review`, `PATCH /scans/{id}` (corrections to marks/team number → re-score, audit), `POST /scans/{id}/confirm`, `POST /scans/{id}/discard`.
   - Duplicates: `GET /events/{code}/duplicates`, `POST /events/{code}/teams/{n}/counted-scan {scan_id}`.
   - Free response: `PUT /events/{code}/teams/{n}/free-response {value}` (0 ≤ value ≤ `free_response_max`, 0.5 steps; update writes audit entry).
   - Results: `GET /events/{code}/results` (team, name, mcq, free response, total, rank, who/when, missing items summary), `GET /events/{code}/results.csv`.
   - Audit: `GET /audit?entity=&entity_id=` (admin).
4. **Reading in the background** — uploads return fast; reading runs in a worker thread pool (FastAPI `BackgroundTasks` or a small `concurrent.futures` pool). Scan rows move `processing → needs_review | confirmed | failed`. Clients poll `GET /scans/{id}` (simple and reliable on phones). Add `processing` and `failed` to the scan status enum via a new migration.
5. **Counting rules**
   - A scan with no flags (other than `blank`) and a valid, non-duplicate team number is auto-confirmed and counted.
   - Anything flagged waits for review.
   - Second scan for a team already counted → `needs_review` with `duplicate_team`; it counts only when a grader picks it (the DB partial unique index from phase 0 guarantees at most one).
6. **Key changes after scans** — if an event is re-imported with a higher `sheet_version` or corrected answers, offer `POST /events/{code}/rescore` that recomputes `mcq_score` for every scan from stored marks, writing audit entries.
7. **Ranking** — rank by total descending; ties share a rank (1, 2, 2, 4). No tiebreakers in v1 (decided).
8. **Hardening** — upload size limit (e.g. 25 MB), accepted content types only, filenames never trusted (random ids), CORS locked to the app origin, security headers, request ids in logs.
9. **OpenAPI** — clean `/docs` page; generate a typed TypeScript client from it in phase 6.

## Tests

- Route tests with `TestClient` for every route: happy path, validation errors, auth required, admin-only.
- Full flow test: login → import A&P → import teams → upload 5 fake sheets (from phase 3) → some auto-confirm, one flagged → correct it → enter free-response totals before and after scans → results and CSV match a hand calculation.
- Duplicate flow; re-score flow; audit entries written for every edit with old and new values.
- Storage: local implementation tested; Supabase implementation tested against a mocked HTTP server (`respx`).
- Postgres: run the whole suite on Postgres in CI (already wired).
- Security tests: wrong PIN, rate limit, cookie flags, path traversal in filenames rejected, oversize upload rejected.

## CI changes

- Add the end-to-end API flow test to the default suite. Add `pip-audit` (or `uv` audit equivalent) for known-vulnerable dependencies.

## By the end of this phase

- [ ] Every action in the spec is possible through the API, shown in `/docs`
- [ ] Graders log in with the PIN and their name; every scan, correction and score records who did it
- [ ] Original images are always kept; storage works locally and against Supabase (mocked in tests)
- [ ] Auto-confirm, review, duplicate and re-score rules behave as described and are tested
- [ ] Results and CSV match a hand-checked example
- [ ] New migration(s) applied and checked for drift; CI green on SQLite and Postgres
- [ ] Summary for Yuvan with a short "how to try it" using `/docs`

## Review checkpoint for Yuvan

- Try the API from the `/docs` page with the sample flow (instructions in the summary).
- Confirm the auto-confirm rule (flag-free scans count without a human look) is acceptable.

## Risks

- Background work in a single web process is lost if the server restarts mid-read; scans stuck in `processing` for > 2 min are retried on startup.
