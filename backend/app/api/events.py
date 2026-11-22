"""Events: import a setup spreadsheet, list events, get the printable sheet, re-score."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import AdminDep, GraderDep
from app.api.deps import get_db, get_settings_dep
from app.api.errors import ApiError, not_found
from app.api.schemas import (
    EventDetailOut,
    EventImportOut,
    EventOut,
    ImportReportOut,
    QuestionOut,
    RescoreOut,
)
from app.api.uploads import read_limited
from app.config import Settings
from app.db.models import Event, Scan, ScanStatus
from app.services.event_import import ImportReport, import_event_workbook
from app.services.event_store import EventLockedError, load_event_setup, save_event
from app.services.layout import build_layout
from app.services.scans import rescore_event
from app.services.sheet_pdf import render_sheet_pdf

router = APIRouter(prefix="/api/events", tags=["events"])
XLSX_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}


def get_event(db: Session, code: str) -> Event:
    event = db.scalars(select(Event).where(Event.code == code)).one_or_none()
    if event is None:
        raise not_found(f"Event {code}")
    return event


def _report_out(report: ImportReport) -> ImportReportOut:
    return ImportReportOut(
        ok=report.ok,
        source=report.source,
        errors=report.errors,
        warnings=report.warnings,
        notes=report.notes,
        tabs_ignored=report.tabs_ignored,
        question_count=report.question_count,
        mcq_points_total=report.mcq_points_total,
        sheet_note=report.sheet_note,
        text=report.to_text(),
    )


def _event_out(db: Session, event: Event) -> dict[str, object]:
    counts = dict(
        db.execute(
            select(Scan.status, func.count()).where(Scan.event_id == event.id).group_by(Scan.status)
        ).all()
    )
    counted = db.scalar(
        select(func.count()).select_from(Scan).where(Scan.event_id == event.id, Scan.is_counted)
    )
    mcq = sum((q.points for q in event.questions), start=0)
    return {
        "code": event.code,
        "name": event.name,
        "tournament": event.tournament,
        "date": event.event_date,
        "sheet_version": event.sheet_version,
        "team_number_digits": event.team_number_digits,
        "total_points": event.total_points,
        "free_response_max": event.free_response_max,
        "mcq_points_total": mcq,
        "question_count": len(event.questions),
        "scans_needing_review": counts.get(ScanStatus.needs_review, 0),
        "scans_counted": counted or 0,
    }


@router.post("/import", response_model=EventImportOut)
async def import_event(
    file: UploadFile,
    admin: AdminDep,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    dry_run: Annotated[bool, Query(description="Check the file without saving")] = False,
) -> EventImportOut:
    """Upload a supervisor's event-setup .xlsx. Returns the import report; saves unless
    ``dry_run`` or the report has problems."""
    if file.content_type not in XLSX_TYPES and not (file.filename or "").endswith(".xlsx"):
        raise ApiError(415, "unsupported_type", "Upload the event setup as an .xlsx file")
    data = await read_limited(file, settings.max_upload_mb)
    name = Path(file.filename or "event_setup.xlsx").name
    return await run_in_threadpool(_import_event, db, data, name, dry_run)


def _import_event(db: Session, data: bytes, name: str, dry_run: bool) -> EventImportOut:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.xlsx"
        path.write_bytes(data)
        report = import_event_workbook(path)
    report.source = name
    out = EventImportOut(report=_report_out(report), saved=False)
    if not report.ok or dry_run or report.setup is None:
        return out
    try:
        result = save_event(db, report.setup, name)
    except EventLockedError as exc:
        db.rollback()
        raise ApiError(409, "event_locked", str(exc)) from exc
    db.commit()
    return out.model_copy(
        update={"saved": True, "action": result.action.value, "event_code": result.code}
    )


@router.get("", response_model=list[EventOut])
def list_events(grader: GraderDep, db: Annotated[Session, Depends(get_db)]) -> list[EventOut]:
    events = db.scalars(select(Event).order_by(Event.code)).all()
    return [EventOut.model_validate(_event_out(db, e)) for e in events]


@router.get("/{code}", response_model=EventDetailOut)
def event_detail(
    code: str, grader: GraderDep, db: Annotated[Session, Depends(get_db)]
) -> EventDetailOut:
    event = get_event(db, code)
    questions = [
        QuestionOut(
            q=q.q,
            points=q.points,
            options=q.options,
            correct=q.correct.split(","),
            scoring=q.scoring.value,
            penalty_per_wrong=q.penalty_per_wrong,
        )
        for q in event.questions
    ]
    return EventDetailOut.model_validate({**_event_out(db, event), "questions": questions})


@router.get("/{code}/sheet.pdf", response_class=Response)
def sheet_pdf(code: str, grader: GraderDep, db: Annotated[Session, Depends(get_db)]) -> Response:
    """The printable bubble sheet. Print at 100% / actual size."""
    event = get_event(db, code)
    layout = build_layout(load_event_setup(db, event.code))
    filename = f"{event.code}_v{event.sheet_version}_answer_sheet.pdf"
    return Response(
        render_sheet_pdf(layout),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{code}/rescore", response_model=RescoreOut)
def rescore(
    code: str,
    admin: AdminDep,
    db: Annotated[Session, Depends(get_db)],
    dry_run: Annotated[bool, Query(description="Only count the scans that would change")] = False,
) -> RescoreOut:
    """Recompute every scan's score after the answer key changed (audited)."""
    changed = rescore_event(db, get_event(db, code), admin.id)
    if dry_run:
        db.rollback()
        return RescoreOut(changed=changed, saved=False)
    db.commit()
    return RescoreOut(changed=changed)
