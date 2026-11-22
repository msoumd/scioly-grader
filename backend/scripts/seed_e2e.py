"""Fresh database for the browser (Playwright) tests: the example A&P event and 12 teams.

    uv run python scripts/seed_e2e.py sqlite:///./data/e2e/e2e.db

Deletes and recreates a SQLite file; refuses any other kind of database so it can never
wipe a real one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db.session import make_engine  # noqa: E402
from app.services.event_import import import_event_workbook  # noqa: E402
from app.services.event_store import save_event  # noqa: E402
from app.services.teams_import import parse_teams_csv, save_teams  # noqa: E402

AP_FILE = BACKEND.parent / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"
TEAMS = "team_number,team_name\n" + "".join(f"{n},E2E Team {n}\n" for n in range(1, 13))


def main(url: str) -> None:
    if not url.startswith("sqlite:///"):
        raise SystemExit("seed_e2e only creates SQLite files (sqlite:///path/to/file.db)")
    path = Path(url.removeprefix("sqlite:///"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")

    setup = import_event_workbook(AP_FILE).setup
    teams = parse_teams_csv(TEAMS.encode())
    assert setup is not None and teams.ok, teams.errors
    engine = make_engine(url)
    with Session(engine) as db:
        save_event(db, setup, AP_FILE.name)
        save_teams(db, teams.teams)
        db.commit()
    engine.dispose()
    print(f"seeded {path}: event {setup.event.event_id}, {len(teams.teams)} teams")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sqlite:///./data/e2e/e2e.db")
