# Phase 9 — Deploy

**Starter-prompt step:** 7 (deploy as a small hosted service with HTTPS)
**Branch:** `phase-09-deploy`
**Depends on:** phase 8 merged
**Status:** everything that needs no account is built on branch `phase-09-deploy`. Creating the Supabase and Render accounts and going live waits for Yuvan (steps in `docs/DEPLOY.md`).

## Goal

The app runs on the internet over HTTPS with Supabase Postgres and Supabase Storage, deploys automatically from `main` after CI passes, and has backups and basic monitoring. **Creating paid accounts or changing production needs Yuvan's explicit go-ahead.**

## Hosting decision (record in `DECISIONS.md`)

- **Database + images:** Supabase project (Postgres + private Storage bucket `scans`). Free tier is likely enough for one tournament (~20 events × 63 teams ≈ 1,300 photos ≈ 2–4 GB of originals — check against the free tier's storage limit; the Pro plan may be needed for the tournament month).
- **App server:** one Docker container (FastAPI serving API + built frontend) on **Render** (simple GitHub-connected deploys, free HTTPS, easy secrets UI). Fly.io is the alternative if Render's cold starts are a problem. Use a paid "always on" instance on tournament day; OpenCV reading needs ~1 GB RAM.
- Same origin for app and API, so one certificate and no CORS.

## Tasks

1. **Dockerfile** (multi-stage): build frontend with Node → Python slim image with `uv` sync `--locked --no-dev`, OpenCV headless; non-root user; `uvicorn` with 2 workers; health check on `/health`.
2. **Startup** runs `alembic upgrade head` before serving (single instance, so no race).
3. **Supabase setup** (with Yuvan): create project in the closest region; create `scans` bucket (private); copy the pooler connection string and service-role key into Render secrets (never into the repo). Confirm RLS is on for all tables (phase 0 migration) and the bucket is not public.
4. **Render setup:** web service from the repo, Docker runtime, env vars: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `TOURNAMENT_PIN`, `ADMIN_PIN`, `SESSION_SECRET`, `STORAGE_BACKEND=supabase`. Custom domain optional.
5. **CD:** GitHub Actions `deploy.yml` — on push to `main`, after CI passes, trigger Render deploy hook (secret `RENDER_DEPLOY_HOOK`), then run a post-deploy smoke test against the live URL (`/health`, login with a smoke-test grader, fetch events).
6. **Staging:** a second Render service + Supabase branch/project for testing deploys before tournament week (optional; recommended if budget allows).
7. **Backups:** Supabase daily backups (Pro) or a nightly GitHub Action `pg_dump` to an encrypted artifact; document restore steps and test a restore once.
8. **Monitoring:** Render logs + a free uptime monitor hitting `/health`; Sentry (free tier) for backend and frontend errors, DSN in env.
9. **Security review:** run `/security-review`-style pass: secrets only in env, cookie flags, upload limits, admin routes protected, Supabase anon key not used anywhere, bucket private, HTTPS-only (HSTS).
10. **Load check:** script that uploads 60 fake sheets concurrently from phase 3 against staging; confirm reading keeps up (< 5 s per sheet end-to-end under load) and memory stays within the instance.

## Tests

- Docker image builds in CI and passes `/health` in a container smoke test.
- Post-deploy smoke test (above).
- Playwright e2e suite can be pointed at staging via `BASE_URL` and passes.

## CI/CD changes

- New `docker` job (build + run + health check) on PRs.
- New `deploy.yml` on `main`.

## By the end of this phase

- [ ] App live at an HTTPS URL; camera works from iPhone Safari on that URL
- [ ] Database and images in Supabase, RLS on, bucket private
- [ ] Merges to `main` deploy automatically after green CI, followed by a passing smoke test *(workflow built; needs the Render hook)*
- [ ] Backups run and a restore has been tested once *(backup + restore tested locally; nightly job runs once secrets are set)*
- [ ] Error monitoring and uptime check active
- [x] Load check results in the summary
- [x] Costs listed for Yuvan (monthly and for tournament week)

## Review checkpoint for Yuvan

- Approve account creation and any paid plan before it happens.
- Open the live URL on your phone and run the mini event from phase 8.

## Risks

- Free-tier sleep/cold starts during the tournament: use the always-on plan for that week.
- Venue Wi-Fi: the upload queue from phase 6 covers short drops; a phone hotspot is the backup.
