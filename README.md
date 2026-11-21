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
    cli.py        command-line import, scoring and sheet tools
  migrations/     Alembic migrations — the only way the schema changes
  tests/
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

The import report lists every problem with its tab and row number. Rules for re-importing and scoring are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Checks

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest
```

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
