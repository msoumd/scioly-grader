"""Scans: upload photos/PDFs, poll the read result, correct, confirm, discard, and
resolve duplicate scans for a team."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import AdminDep, GraderDep
from app.api.deps import get_db, get_queue, get_settings_dep, get_storage
from app.api.errors import ApiError, not_found
from app.api.events import get_event
from app.api.schemas import (
    CorrectionIn,
    CountedScanIn,
    DuplicateOut,
    QuestionReadOut,
    ScanCreated,
    ScanOut,
    ScanSummary,
    UploadOut,
)
from app.api.uploads import CONTENT_TYPES, read_limited, scan_kind
from app.config import Settings
from app.db.models import Event, Grader, Scan, ScanStatus, Team
from app.services import scans as rules
from app.services.detection.loader import PDFIUM_LOCK
from app.services.reading import ReadingQueue
from app.services.storage import Storage

router = APIRouter(prefix="/api", tags=["scans"])
MAX_PDF_PAGES = 60

Db = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[Storage, Depends(get_storage)]


def _pdf_pages(data: bytes) -> int:
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:  # PDFium is not thread-safe
        try:
            doc = pdfium.PdfDocument(data)
        except Exception as exc:
            raise ApiError(415, "unreadable_pdf", "That PDF could not be opened") from exc
        try:
            return len(doc)
        finally:
            doc.close()


def get_scan(db: Session, scan_id: int) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise not_found(f"Scan #{scan_id}")
    return scan


def _grader_names(db: Session, ids: set[int]) -> dict[int, str]:
    return dict(db.execute(select(Grader.id, Grader.name).where(Grader.id.in_(ids))).all())


def _summary(scan: Scan, names: dict[int, str]) -> ScanSummary:
    return ScanSummary(
        id=scan.id,
        status=scan.status,
        is_counted=scan.is_counted,
        team_number=scan.team_number,
        mcq_score=scan.mcq_score,
        flags=list(scan.flags or []),
        grader=names.get(scan.grader_id, "?"),
        updated_at=scan.updated_at,
    )


def scan_out(db: Session, scan: Scan, storage: Storage) -> ScanOut:
    event = db.get(Event, scan.event_id)
    assert event is not None
    detected = scan.detected_marks or {}
    overrides = (scan.corrections or {}).get("marks") or {}
    effective = rules.effective_marks(scan)
    questions = []
    for q, info in sorted(detected.get("questions", {}).items(), key=lambda kv: int(kv[0])):
        crop = info.get("crop")
        questions.append(
            QuestionReadOut(
                q=int(q),
                marked=sorted(effective.get(int(q), set())),
                detected=info.get("marked", []),
                corrected=q in overrides,
                fills=info.get("fills", {}),
                confidence=info.get("confidence"),
                flags=info.get("flags", []),
                crop_url=storage.url(crop) if crop else None,
            )
        )
    grader = db.get(Grader, scan.grader_id)
    return ScanOut(
        id=scan.id,
        event_code=event.code,
        status=scan.status,
        is_counted=scan.is_counted,
        team_number=scan.team_number,
        mcq_score=scan.mcq_score,
        flags=list(scan.flags or []),
        page=scan.page,
        error=scan.error,
        grader=grader.name if grader else "?",
        created_at=scan.created_at,
        updated_at=scan.updated_at,
        original_url=storage.url(scan.image_path),
        warped_url=storage.url(scan.warped_path) if scan.warped_path else None,
        page_flags=detected.get("page_flags", []),
        team=detected.get("team", {}),
        questions=questions,
    )


@router.post("/scans", response_model=UploadOut, status_code=202)
async def upload_scan(
    file: UploadFile,
    grader: GraderDep,
    db: Db,
    storage: StorageDep,
    queue: Annotated[ReadingQueue, Depends(get_queue)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    event_code: Annotated[str, Form(description="The event the grader is scoring")],
) -> UploadOut:
    """Upload a photo, scan or multi-page PDF. Returns at once with one scan per page
    (status ``processing``); poll ``GET /api/scans/{id}`` for the result."""
    event = get_event(db, event_code)
    data = await read_limited(file, settings.max_upload_mb)
    ext = scan_kind(data)
    pages = _pdf_pages(data) if ext == ".pdf" else 1
    if pages < 1 or pages > MAX_PDF_PAGES:
        raise ApiError(422, "bad_page_count", f"PDF must have 1-{MAX_PDF_PAGES} pages")
    key = f"uploads/{secrets.token_hex(12)}/original{ext}"  # never the client's filename
    storage.put(key, data, CONTENT_TYPES[ext])
    created = [
        Scan(
            event_id=event.id,
            sheet_version=event.sheet_version,
            image_path=key,
            page=p,
            grader_id=grader.id,
            status=ScanStatus.processing,
            detected_marks={},
            corrections={},
            flags=[],
        )
        for p in range(1, pages + 1)
    ]
    db.add_all(created)
    db.commit()
    for scan in created:
        queue.submit(scan.id)
    for scan in created:
        db.refresh(scan)
    return UploadOut(scans=[ScanCreated(id=s.id, page=s.page, status=s.status) for s in created])


@router.get("/scans/{scan_id}", response_model=ScanOut)
def read_scan(scan_id: int, grader: GraderDep, db: Db, storage: StorageDep) -> ScanOut:
    """The read result: marks per question (after corrections), flags, crop images, score."""
    return scan_out(db, get_scan(db, scan_id), storage)


@router.get("/events/{code}/scans", response_model=list[ScanSummary])
def event_scans(
    code: str,
    grader: GraderDep,
    db: Db,
    status: Annotated[ScanStatus | None, Query()] = None,
) -> list[ScanSummary]:
    event = get_event(db, code)
    query = select(Scan).where(Scan.event_id == event.id).order_by(Scan.id)
    if status is not None:
        query = query.where(Scan.status == status)
    scans = db.scalars(query).all()
    names = _grader_names(db, {s.grader_id for s in scans})
    return [_summary(s, names) for s in scans]


@router.patch("/scans/{scan_id}", response_model=ScanOut)
def correct_scan(
    scan_id: int, body: CorrectionIn, grader: GraderDep, db: Db, storage: StorageDep
) -> ScanOut:
    """Fix marks and/or the team number from the review screen; the score is recomputed
    and every change is recorded in the audit log."""
    scan = get_scan(db, scan_id)
    event = db.get(Event, scan.event_id)
    assert event is not None
    setup = rules.setup_for(db, event)
    rules.correct(
        db,
        scan,
        setup,
        grader.id,
        body.marks,
        body.team_number,
        "team_number" in body.model_fields_set,
    )
    db.commit()
    return scan_out(db, scan, storage)


@router.post("/scans/{scan_id}/confirm", response_model=ScanOut)
def confirm_scan(scan_id: int, grader: GraderDep, db: Db, storage: StorageDep) -> ScanOut:
    """A grader has checked this scan: it now counts for its team."""
    scan = get_scan(db, scan_id)
    rules.confirm(db, scan, grader.id, rules.team_numbers(db))
    db.commit()
    return scan_out(db, scan, storage)


@router.post("/scans/{scan_id}/discard", response_model=ScanOut)
def discard_scan(scan_id: int, grader: GraderDep, db: Db, storage: StorageDep) -> ScanOut:
    """Bad photo or unwanted duplicate: keep the image but never count it."""
    scan = get_scan(db, scan_id)
    rules.discard(db, scan, grader.id)
    db.commit()
    return scan_out(db, scan, storage)


@router.get("/events/{code}/duplicates", response_model=list[DuplicateOut])
def duplicates(code: str, grader: GraderDep, db: Db) -> list[DuplicateOut]:
    """Teams with more than one scan that is not discarded."""
    event = get_event(db, code)
    live = (
        Scan.event_id == event.id,
        Scan.status != ScanStatus.discarded,
        Scan.team_number.is_not(None),
    )
    teams = db.scalars(
        select(Scan.team_number)
        .where(*live)
        .group_by(Scan.team_number)
        .having(func.count() > 1)
        .order_by(Scan.team_number)
    ).all()
    out = []
    for team in teams:
        scans = db.scalars(
            select(Scan).where(*live, Scan.team_number == team).order_by(Scan.id)
        ).all()
        names = _grader_names(db, {s.grader_id for s in scans})
        team_row = db.scalars(select(Team).where(Team.team_number == team)).one_or_none()
        out.append(
            DuplicateOut(
                team_number=team or 0,
                team_name=team_row.name if team_row else None,
                scans=[_summary(s, names) for s in scans],
            )
        )
    return out


@router.post("/events/{code}/teams/{team_number}/counted-scan", response_model=ScanOut)
def choose_counted_scan(
    code: str,
    team_number: int,
    body: CountedScanIn,
    admin: AdminDep,
    db: Db,
    storage: StorageDep,
) -> ScanOut:
    """Supervisor picks which scan counts for a team; the team's other scans are discarded."""
    event = get_event(db, code)
    scan = get_scan(db, body.scan_id)
    rules.choose_counted(db, event, team_number, scan, admin.id)
    db.commit()
    return scan_out(db, scan, storage)
