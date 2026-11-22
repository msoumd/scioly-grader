"""Teams: import the one-time CSV, list teams."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AdminDep, GraderDep
from app.api.deps import get_db, get_settings_dep
from app.api.schemas import TeamOut, TeamsImportOut
from app.api.uploads import read_limited
from app.config import Settings
from app.db.models import Team
from app.services.teams_import import parse_teams_csv, save_teams

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.post("/import", response_model=TeamsImportOut)
async def import_teams(
    file: UploadFile,
    admin: AdminDep,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    dry_run: Annotated[bool, Query(description="Check the file without saving")] = False,
) -> TeamsImportOut:
    """Upload ``team_number,team_name`` CSV. Saved only if every line is valid (and not
    ``dry_run``)."""
    data = await read_limited(file, settings.max_upload_mb)
    name = Path(file.filename or "teams.csv").name
    return await run_in_threadpool(_import_teams, db, data, name, dry_run)


def _import_teams(db: Session, data: bytes, name: str, dry_run: bool) -> TeamsImportOut:
    report = parse_teams_csv(data, name)
    out = TeamsImportOut(
        ok=report.ok, errors=report.errors, warnings=report.warnings, text=report.to_text()
    )
    if not report.ok:
        return out
    result = save_teams(db, report.teams)
    if dry_run:
        db.rollback()
        return out.model_copy(
            update={
                "inserted": result.inserted,
                "updated": result.updated,
                "warnings": [*report.warnings, *result.warnings],
                "saved": False,
            }
        )
    db.commit()
    return out.model_copy(
        update={
            "inserted": result.inserted,
            "updated": result.updated,
            "warnings": [*report.warnings, *result.warnings],
            "saved": True,
        }
    )


@router.get("", response_model=list[TeamOut])
def list_teams(grader: GraderDep, db: Annotated[Session, Depends(get_db)]) -> list[TeamOut]:
    return [
        TeamOut(team_number=t.team_number, name=t.name)
        for t in db.scalars(select(Team).order_by(Team.team_number))
    ]
