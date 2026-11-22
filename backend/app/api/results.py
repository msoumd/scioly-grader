"""Free-response totals, the results table and its CSV, and the audit log."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AdminDep, GraderDep
from app.api.deps import get_db
from app.api.errors import ApiError, not_found
from app.api.events import get_event
from app.api.schemas import AuditOut, FreeResponseIn, FreeResponseOut, ResultRow, ResultsOut
from app.db.models import AuditLog, FreeResponseScore, Grader, Team
from app.services.results import pending_reviews, results, results_csv
from app.services.scans import audit

router = APIRouter(prefix="/api", tags=["results"])
Db = Annotated[Session, Depends(get_db)]


@router.put("/events/{code}/teams/{team_number}/free-response", response_model=FreeResponseOut)
def set_free_response(
    code: str, team_number: int, body: FreeResponseIn, grader: GraderDep, db: Db
) -> FreeResponseOut:
    """Enter or change a team's free-response total (0 to the event's maximum, 0.5 steps).
    Changing an existing value is recorded in the audit log."""
    event = get_event(db, code)
    if db.scalars(select(Team).where(Team.team_number == team_number)).one_or_none() is None:
        raise not_found(f"Team {team_number}")
    value = body.value
    if value > event.free_response_max:
        raise ApiError(
            422, "over_max", f"Free response is out of {event.free_response_max}; got {value}"
        )
    if (value * 2) % 1 != 0:
        raise ApiError(422, "half_points", "Free response must be in steps of 0.5")
    row = db.scalars(
        select(FreeResponseScore).where(
            FreeResponseScore.event_id == event.id, FreeResponseScore.team_number == team_number
        )
    ).one_or_none()
    if row is None:
        row = FreeResponseScore(
            event_id=event.id, team_number=team_number, value=value, grader_id=grader.id
        )
        db.add(row)
        db.flush()
        audit(db, "free_response_score", row.id, "value", None, value, grader.id)
    else:
        audit(db, "free_response_score", row.id, "value", Decimal(row.value), value, grader.id)
        row.value, row.grader_id = value, grader.id
    db.commit()
    db.refresh(row)
    return FreeResponseOut(
        team_number=team_number,
        value=Decimal(row.value),
        grader=grader.name,
        updated_at=row.updated_at,
    )


@router.get("/events/{code}/results", response_model=ResultsOut)
def get_results(code: str, grader: GraderDep, db: Db) -> ResultsOut:
    """Every team: multiple choice, free response, total and rank (ties share a rank)."""
    event = get_event(db, code)
    rows = results(db, event)
    out = [
        ResultRow(
            rank=r.rank,
            team_number=r.team_number,
            team_name=r.team_name,
            mcq=r.mcq,
            free_response=r.free_response,
            total=r.total,
            missing=r.missing,
            mcq_by=r.mcq_by,
            mcq_at=r.mcq_at,
            free_response_by=r.fr_by,
            free_response_at=r.fr_at,
            scan_id=r.scan_id,
            free_response_id=r.free_response_id,
        )
        for r in rows
    ]
    complete = sum(1 for r in rows if not r.missing)
    return ResultsOut(
        event_code=event.code,
        total_points=event.total_points,
        rows=out,
        teams_complete=complete,
        teams_missing_something=len(rows) - complete,
        teams_without_scan=sum(1 for r in rows if r.mcq is None),
        teams_without_free_response=sum(1 for r in rows if r.free_response is None),
        scans_needing_review=pending_reviews(db, event),
    )


@router.get("/events/{code}/results.csv", response_class=Response)
def get_results_csv(code: str, grader: GraderDep, db: Db) -> Response:
    event = get_event(db, code)
    return Response(
        results_csv(results(db, event)).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{event.code}_results.csv"'},
    )


@router.get(
    "/events/{code}/teams/{team_number}/free-response/history", response_model=list[AuditOut]
)
def free_response_history(code: str, team_number: int, grader: GraderDep, db: Db) -> list[AuditOut]:
    """Every entry and change of this team's free-response total, oldest first."""
    event = get_event(db, code)
    row = db.scalars(
        select(FreeResponseScore).where(
            FreeResponseScore.event_id == event.id, FreeResponseScore.team_number == team_number
        )
    ).one_or_none()
    if row is None:
        return []
    found = db.execute(
        select(AuditLog, Grader.name)
        .join(Grader, Grader.id == AuditLog.grader_id)
        .where(AuditLog.entity == "free_response_score", AuditLog.entity_id == row.id)
        .order_by(AuditLog.id)
    ).all()
    return [
        AuditOut(
            id=a.id,
            entity=a.entity,
            entity_id=a.entity_id,
            field=a.field,
            old_value=a.old_value,
            new_value=a.new_value,
            grader=name,
            created_at=a.created_at,
        )
        for a, name in found
    ]


@router.get("/audit", response_model=list[AuditOut])
def get_audit(
    admin: AdminDep,
    db: Db,
    entity: Annotated[str | None, Query()] = None,
    entity_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AuditOut]:
    """Every edit to an existing score: who, when, old and new value (newest first)."""
    query = select(AuditLog, Grader.name).join(Grader, Grader.id == AuditLog.grader_id)
    if entity:
        query = query.where(AuditLog.entity == entity)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    rows = db.execute(query.order_by(AuditLog.id.desc()).limit(limit)).all()
    return [
        AuditOut(
            id=a.id,
            entity=a.entity,
            entity_id=a.entity_id,
            field=a.field,
            old_value=a.old_value,
            new_value=a.new_value,
            grader=name,
            created_at=a.created_at,
        )
        for a, name in rows
    ]
