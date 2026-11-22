# scioly-grader

Scores Science Olympiad multiple-choice bubble sheets from phone photos and combines them with a human-entered free-response total.

- Spec and build order: [`docs/STARTER_PROMPT.md`](docs/STARTER_PROMPT.md)
- Why things are the way they are: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Build phases (one plan per session): [`docs/sessions/`](docs/sessions/README.md)
- Example event setup spreadsheets: [`event_setups/`](event_setups/README.md)

## Layout

```
backend/
  app/
    api/          FastAPI routes
    db/           SQLAlchemy models + session (SQLite dev, Supabase Postgres prod)
    schemas/      Pydantic shapes, e.g. the event-setup import
    services/     scoring, event/teams import (phase 1), sheet layout + PDF (phase 2),
                  detection (phases 3-4)
    api/          HTTP routes: login, events, teams, scans, review, results (phase 5)
    services/detection/  reading photos: markers, QR, bubbles, flags (phase 4)
    harness/      fake filled sheets, phone-photo simulation, reader evaluation (phase 3)
    web.py        serves the built phone app at "/"
    cli.py        command-line import, scoring and sheet tools
  migrations/     Alembic migrations — the only way the schema changes
  scripts/        browser-test database and fixtures, OpenAPI export
  tests/
frontend/         phone app (Vite + React + TypeScript, installable PWA) (phase 6)
  src/api/        typed API client (types generated from the backend's OpenAPI)
  src/lib/        corner-marker detection, steadiness check, offline upload queue
  e2e/            Playwright browser tests
event_setups/     example supervisor spreadsheets (the app works for any event)
docs/
```

## Run locally

Needs [uv](https://docs.astral.sh/uv/).

```bash
cd backend
cp .env.example .env        # then edit; .env is git-ignored
uv sync
uv run alembic upgrade head # creates scioly.db
uv run uvicorn app.main:app --reload
```

Then open http://localhost:8000/health.

## Import an event and try scoring

```bash
cd backend
uv run python -m app.cli import-event ../event_setups/PUSO_2026_AP_event_setup.xlsx          # check only
uv run python -m app.cli import-event ../event_setups/PUSO_2026_AP_event_setup.xlsx --save   # save to the database
uv run python -m app.cli import-teams path/to/teams.csv --save                               # team_number,team_name
uv run python -m app.cli score-demo AP "1=D,2=A,9=C,D"                                       # score some marks
```

Print an answer sheet (print at 100% / actual size):

```bash
uv run python -m app.cli make-sheet AP                                                     # saved event
uv run python -m app.cli make-sheet --from-xlsx ../event_setups/PUSO_2026_AP_event_setup.xlsx --png
```

PDFs go to `backend/data/generated/` (git-ignored). CI also attaches every example event's sheet to each pull request as an `answer-sheets` artifact.

The import report lists every problem with its tab and row number.

## Try the API from your browser

The whole app is available as a web API, with a clickable page at `/docs`:

```bash
cd backend
cp .env.example .env   # set TOURNAMENT_PIN, ADMIN_PIN, SESSION_SECRET; for http://localhost also COOKIE_SECURE=false
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000/docs, then on that page, in order:
1. `POST /api/login` with the admin PIN and a name. The login cookie is kept for the next calls.
2. `POST /api/events/import`: upload `event_setups/PUSO_2026_AP_event_setup.xlsx`.
3. `POST /api/teams/import`: upload a `team_number,team_name` CSV.
4. `GET /api/events/AP/sheet.pdf` to print a sheet. Fill it in and photograph it, or make a fake photo with `python -m app.harness build`.
5. `POST /api/scans` with `event_code=AP` and the photo, then `GET /api/scans/{id}` for the result.
6. `PUT /api/events/AP/teams/{n}/free-response`, then `GET /api/events/AP/results` (or `results.csv`).

## Run the phone app

Needs [Node.js](https://nodejs.org) 22 as well as uv.

**One server, like production** (the API serves the built app at `/`):

```bash
cd frontend && npm ci && npm run build      # -> frontend/dist
cd ../backend && uv run uvicorn app.main:app  # open http://localhost:8000
```

**While changing the app** (instant reload; Vite passes `/api` on to the backend):

```bash
cd backend && uv run uvicorn app.main:app --reload   # with COOKIE_SECURE=false in .env
cd frontend && npm run dev                           # open http://localhost:5173
```

**On your iPhone.** Safari only allows the camera on an `https://` address, so a plain `http://192.168...` link shows "camera needs a secure link" (uploading photos still works). The easiest way is a temporary HTTPS tunnel to the one-server setup above, for example [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/):

```bash
cloudflared tunnel --url http://localhost:8000      # prints an https://....trycloudflare.com link
```

Open that link on the phone, log in, then use Safari's Share > Add to Home Screen to install it as an app. Anyone with the link can reach your laptop while the tunnel runs, so use a real PIN and stop the tunnel afterwards.

On the Scan screen, **Start camera** and hold the phone over a printed sheet. The four corner targets turn green as each corner marker is found, and the picture is taken by itself once the sheet is steady. **Upload photos or PDF** accepts iPhone photos (including HEIC) and multi-page PDFs. Uploads are kept on the phone until the server has them, so a Wi-Fi drop only delays them.

The **Review** tab (with a count badge) lists sheets that need a person, oldest first, with the reasons. Opening one shows the crop of each unclear answer with tap-to-fix bubbles, the team number (with a number pad if it couldn't be read), and the live score. Then **Confirm and count**, **Retake** or **Discard**. Teams with two sheets can be compared there, and a supervisor (admin PIN) picks the one that counts.

The **Scores** tab is where graders type each team's free-response total. The **Results** tab shows the ranked table, what is still missing, **Download CSV** and **Print**. A supervisor can set up everything from the app under **Event setup** (on the event list, or on the Results tab): import the event spreadsheet and teams list, download answer sheets, and re-score after a key change. The command line is no longer needed.

## Put it online

See [`docs/DEPLOY.md`](docs/DEPLOY.md): Supabase for data and photos, Render for the app, GitHub for automatic deploys and nightly backups, with costs. To try the production container locally:

```bash
docker build -t scioly-grader .
docker run -p 8000:8000 -e TOURNAMENT_PIN=246810 -e ADMIN_PIN=13579135 -e SESSION_SECRET=$(openssl rand -hex 32) \
  -e COOKIE_SECURE=false -e DATABASE_URL=sqlite:////app/backend/data/app.db scioly-grader
```

## Read a sheet

```bash
uv run python -m app.cli read-sheet photo.jpg                       # event from the QR, looked up in the database
uv run python -m app.cli read-sheet scans.pdf --from-xlsx ../event_setups/PUSO_2026_AP_event_setup.xlsx
uv run python -m app.cli read-sheet photo.heic --json --warped-out straightened.png
```

It prints the event, team number, each question's marks with a confidence, anything flagged for review, and the multiple-choice score. Photos (JPEG/PNG/iPhone HEIC) and multi-page PDFs work. If the page can't be found, it asks for a retake. How it decides, and the thresholds used, are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Fake-sheet test harness

Builds fake phone photos of filled-in sheets with known answers, and measures a reader against them:

```bash
uv run python -m app.harness build --from-xlsx ../event_setups/PUSO_2026_AP_event_setup.xlsx --n 200   # -> data/harness/AP
uv run python -m app.harness contact-sheet --dataset data/harness/AP
uv run python -m app.harness evaluate --dataset data/harness/AP --reader detector   # or oracle / blank
```

To add real phone photos as test data, see [`backend/data/real_samples/README.md`](backend/data/real_samples/README.md). CI attaches contact sheets and reports to every PR as `harness-samples`. Rules for re-importing and scoring are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Checks

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest
```

Phone app:

```bash
cd frontend
npm run lint && npm run typecheck && npm test
npm run build && npm run e2e     # browser tests (first time: npx playwright install chromium webkit)
```

The browser tests start their own backend on a fresh SQLite database with the example event (`backend/scripts/seed_e2e.py`). They use fake sheet photos, a 3-page PDF and a fake camera video made by `backend/scripts/e2e_assets.py`. After changing the API, run `npm run api-types` so the app's types match (CI checks this).

To also run the database tests against Postgres (CI does this):

```bash
docker run -d --rm --name sg-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=sg -p 55432:5432 postgres:16-alpine
TEST_POSTGRES_URL=postgresql+psycopg://postgres:test@localhost:55432/sg uv run pytest
```

## Database changes

Edit `app/db/models.py`, then:

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `migrations/versions/` before committing. CI fails if models and migrations drift apart.
