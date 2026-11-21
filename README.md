# scioly-grader

Scores Science Olympiad multiple-choice bubble sheets from phone photos and combines them with a human-entered free-response total.

- Spec and build order: [`docs/STARTER_PROMPT.md`](docs/STARTER_PROMPT.md)
- Why things are the way they are: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Build phases (one plan per session): [`docs/sessions/`](docs/sessions/README.md)
- Event setup spreadsheets: [`event_setups/`](event_setups/)

## Layout

```
backend/
  app/
    api/          FastAPI routes
    db/           SQLAlchemy models + session (SQLite dev, Supabase Postgres prod)
    schemas/      Pydantic shapes, e.g. the event-setup import
    services/     scoring, import, detection (build steps 1-3)
  migrations/     Alembic migrations — the only way the schema changes
  tests/
event_setups/     supervisor spreadsheets (A&P is the first real event)
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
