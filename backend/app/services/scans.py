"""Scan life cycle and counting rules (independent of HTTP).

processing -> needs_review | confirmed | failed ; any -> discarded

- A scan with no review flags and a valid team number that is not already counted is
  confirmed and counted automatically.
- Anything flagged waits for a human. A second scan for a team that is already counted
  waits as ``duplicate_team`` and counts only when a supervisor picks it.
- Every change to an existing score (corrections, confirm, discard, duplicate choice,
  re-score) writes an audit row with the old and new value and who made it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import AuditLog, Event, Scan, ScanStatus, Team
from app.schemas.event_setup import LETTERS, EventSetup
from app.services.detection import SheetScan, load_images, read_sheet
from app.services.event_store import load_event_setup
from app.services.scoring import score_sheet
from app.services.storage import Storage

# Page flags that do not by themselves need a human (the page was still read reliably).
INFO_PAGE_FLAGS = frozenset({"marker_missing", "image_blurry", "event_unknown"})


# --- helpers -------------------------------------------------------------------


def audit(
    db: Session, entity: str, entity_id: int, field: str, old: object, new: object, grader_id: int
) -> None:
    def text(v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, list | tuple | set):
            return ",".join(str(x) for x in sorted(v))
        return str(v)

    if text(old) == text(new):
        return
    db.add(
        AuditLog(
            entity=entity,
            entity_id=entity_id,
            field=field,
            old_value=text(old),
            new_value=text(new),
            grader_id=grader_id,
        )
    )


def setup_for(db: Session, event: Event) -> EventSetup:
    return load_event_setup(db, event.code)


def team_numbers(db: Session) -> set[int]:
    return set(db.scalars(select(Team.team_number)))


def effective_marks(scan: Scan) -> dict[int, set[str]]:
    """Detected marks with any human corrections applied on top."""
    detected = (scan.detected_marks or {}).get("questions", {})
    marks = {int(q): set(info.get("marked", [])) for q, info in detected.items()}
    for q, letters in ((scan.corrections or {}).get("marks") or {}).items():
        marks[int(q)] = set(letters)
    return marks


def rescore(scan: Scan, setup: EventSetup) -> Decimal:
    marks = effective_marks(scan)
    known = {q.q for q in setup.questions}
    return score_sheet({q: v for q, v in marks.items() if q in known}, setup).total


def counted_scan(db: Session, event_id: int, team_number: int) -> Scan | None:
    return db.scalars(
        select(Scan).where(
            Scan.event_id == event_id, Scan.team_number == team_number, Scan.is_counted
        )
    ).one_or_none()


def _png(img: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".png", img)
    if not ok:  # pragma: no cover
        raise RuntimeError("PNG encoding failed")
    return data.tobytes()


# --- reading -------------------------------------------------------------------


def _store_images(scan: Scan, result: SheetScan, storage: Storage) -> dict[int | str, str]:
    """Straightened page, the team-number block, and crops of the questions a human
    must look at."""
    crops: dict[int | str, str] = {}
    if result.warped is not None:
        key = f"scans/{scan.id}/warped.png"
        storage.put(key, _png(result.warped), "image/png")
        scan.warped_path = key
    for q in result.flagged_questions:
        crop = result.crop(q)
        if crop is not None and crop.size:
            key = f"scans/{scan.id}/crop_{q}.png"
            storage.put(key, _png(crop), "image/png")
            crops[q] = key
    team = result.team_crop()
    if team is not None and team.size:
        key = f"scans/{scan.id}/crop_team.png"
        storage.put(key, _png(team), "image/png")
        crops["team"] = key
    return crops


def apply_read(
    db: Session, scan: Scan, result: SheetScan, storage: Storage, valid_teams: set[int]
) -> None:
    """Store a reader result on a scan, then apply the counting rules."""
    flags: list[str] = []
    if result.event_code and result.setup is not None:
        qr_event = db.scalars(select(Event).where(Event.code == result.event_code)).one_or_none()
        if qr_event is not None and qr_event.id != scan.event_id:
            scan.event_id = qr_event.id  # the sheet says which event it is
            flags.append("event_mismatch")
    crops = _store_images(scan, result, storage)
    scan.detected_marks = {
        "event_code": result.event_code,
        "sheet_version": result.sheet_version,
        "page_flags": result.page_flags,
        "markers_found": list(result.markers_found),
        "mark_level": result.mark_level,
        "sharpness": result.sharpness,
        "team": {
            "number": result.team_number,
            "flags": result.team_flags,
            "crop": crops.get("team"),
            "digits": [
                {"digit": d.digit, "fills": d.fills, "flags": d.flags} for d in result.digits
            ],
        },
        "questions": {
            str(q): {
                "marked": r.marked,
                "fills": r.fills,
                "confidence": r.confidence,
                "flags": r.flags,
                "crop": crops.get(q),
            }
            for q, r in result.questions.items()
        },
    }
    scan.team_number = result.team_number
    if result.sheet_version is not None:
        scan.sheet_version = result.sheet_version
    scan.error = None

    if not result.readable:
        flags.append("retake")
    flags += [f for f in result.page_flags if f not in INFO_PAGE_FLAGS]
    flags += result.team_flags
    flags += [
        f"q{q}:{f}"
        for q, r in result.questions.items()
        for f in r.flags
        if r.needs_review and f != "blank"
    ]
    scan.flags = list(dict.fromkeys(flags))
    scan.mcq_score = result.mcq_score if result.readable else None
    unknown_team = (
        scan.team_number is not None and valid_teams and scan.team_number not in valid_teams
    )
    if unknown_team and "team_unknown" not in scan.flags:
        scan.flags = [*scan.flags, "team_unknown"]
    _auto_count(db, scan)


def _auto_count(db: Session, scan: Scan) -> None:
    if scan.flags or scan.team_number is None or scan.mcq_score is None:
        scan.status = ScanStatus.needs_review
        return
    if counted_scan(db, scan.event_id, scan.team_number) is not None:
        scan.flags = [*scan.flags, "duplicate_team"]
        scan.status = ScanStatus.needs_review
        return
    scan.status, scan.is_counted = ScanStatus.confirmed, True
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:  # another upload for this team was counted at the same moment
        scan.is_counted = False
        scan.flags = [*scan.flags, "duplicate_team"]
        scan.status = ScanStatus.needs_review


def process_scan(db: Session, scan_id: int, storage: Storage) -> None:
    """Read one uploaded page. Never raises: failures become status ``failed``."""
    scan = db.get(Scan, scan_id)
    if scan is None or scan.status != ScanStatus.processing:
        return
    try:
        event = db.get(Event, scan.event_id)
        assert event is not None
        fallback = setup_for(db, event)

        def lookup(code: str, version: int) -> EventSetup | None:
            try:
                setup = load_event_setup(db, code)
            except LookupError:
                return None
            return setup if setup.event.sheet_version == version else None

        pages = load_images(storage.get(scan.image_path), scan.image_path)
        if scan.page > len(pages):
            raise ValueError(f"upload has {len(pages)} page(s), no page {scan.page}")
        result = read_sheet(pages[scan.page - 1], lookup, fallback=fallback)
        apply_read(db, scan, result, storage, team_numbers(db))
    except Exception as exc:  # reading must never take the server down
        db.rollback()
        scan = db.get(Scan, scan_id)
        if scan is None:
            return
        scan.status, scan.is_counted = ScanStatus.failed, False
        scan.error = f"{type(exc).__name__}: {exc}"[:500]
    db.commit()


# --- human actions -------------------------------------------------------------


def _editable(scan: Scan) -> None:
    if scan.status in (ScanStatus.processing, ScanStatus.failed):
        raise ApiError(409, "not_ready", f"Scan is {scan.status.value}; it cannot be edited yet")


def correct(
    db: Session,
    scan: Scan,
    setup: EventSetup,
    grader_id: int,
    marks: dict[int, list[str]] | None,
    team_number: int | None,
    set_team: bool,
) -> None:
    """Apply review-screen corrections, re-score, and audit each change."""
    _editable(scan)
    questions = {q.q: q for q in setup.questions}
    corrections: dict[str, Any] = dict(scan.corrections or {})
    if marks:
        before = effective_marks(scan)
        overrides = dict(corrections.get("marks") or {})
        for q, letters in marks.items():
            if q not in questions:
                raise ApiError(422, "unknown_question", f"Question {q} is not on this sheet")
            allowed = LETTERS[: questions[q].options]
            clean = sorted({x.strip().upper() for x in letters if x.strip()})
            bad = [x for x in clean if x not in allowed]
            if bad:
                raise ApiError(
                    422, "bad_letter", f"Question {q}: {','.join(bad)} is not one of {allowed}"
                )
            overrides[str(q)] = clean
            audit(db, "scan", scan.id, f"q{q}", before.get(q, set()), clean, grader_id)
        corrections["marks"] = overrides
    if set_team:
        if team_number is not None and team_number < 0:
            raise ApiError(422, "bad_team", "Team number cannot be negative")
        audit(db, "scan", scan.id, "team_number", scan.team_number, team_number, grader_id)
        if team_number != scan.team_number:
            corrections["team_number"] = team_number
            if scan.is_counted:  # counted for the old team: must be confirmed again
                audit(db, "scan", scan.id, "is_counted", True, False, grader_id)
                scan.is_counted = False
                scan.status = ScanStatus.needs_review
            scan.team_number = team_number
    scan.corrections = corrections
    new_score = rescore(scan, setup) if scan.detected_marks.get("questions") else None
    audit(db, "scan", scan.id, "mcq_score", scan.mcq_score, new_score, grader_id)
    scan.mcq_score = new_score


def confirm(
    db: Session,
    scan: Scan,
    grader_id: int,
    valid_teams: set[int],
    accept_unknown_team: bool = False,
) -> None:
    """A human has checked the scan: count it (unless another scan already counts).

    A team number missing from the teams list is refused unless the grader explicitly
    accepts it (a team added late, or a list with a typo); that choice is audited."""
    _editable(scan)
    if scan.status == ScanStatus.discarded:
        raise ApiError(409, "discarded", "This scan was discarded")
    if scan.mcq_score is None:
        raise ApiError(409, "unreadable", "This page could not be read; retake the photo")
    if scan.team_number is None:
        raise ApiError(409, "team_missing", "Set the team number before confirming")
    if valid_teams and scan.team_number not in valid_teams:
        if not accept_unknown_team:
            raise ApiError(409, "team_unknown", f"Team {scan.team_number} is not on the teams list")
        audit(db, "scan", scan.id, "accepted_unknown_team", None, scan.team_number, grader_id)
    other = counted_scan(db, scan.event_id, scan.team_number)
    if other is not None and other.id != scan.id:
        raise ApiError(
            409,
            "duplicate_team",
            f"Team {scan.team_number} already has a counted scan (#{other.id}); "
            "a supervisor chooses which one counts",
            other_scan_id=other.id,
        )
    audit(db, "scan", scan.id, "status", scan.status.value, "confirmed", grader_id)
    audit(db, "scan", scan.id, "is_counted", scan.is_counted, True, grader_id)
    scan.status, scan.is_counted = ScanStatus.confirmed, True
    db.flush()


def discard(db: Session, scan: Scan, grader_id: int, reason: str | None = None) -> None:
    if scan.status == ScanStatus.processing:
        raise ApiError(409, "not_ready", "Scan is still being read")
    if reason:
        scan.corrections = {**(scan.corrections or {}), "discard_reason": reason}
        audit(db, "scan", scan.id, "discard_reason", None, reason, grader_id)
    audit(db, "scan", scan.id, "status", scan.status.value, "discarded", grader_id)
    audit(db, "scan", scan.id, "is_counted", scan.is_counted, False, grader_id)
    scan.status, scan.is_counted = ScanStatus.discarded, False


def reopen(db: Session, scan: Scan, grader_id: int) -> None:
    """Supervisor re-opens a confirmed scan for correction; it stops counting until it
    is confirmed again."""
    if scan.status != ScanStatus.confirmed:
        raise ApiError(409, "not_confirmed", f"Scan is {scan.status.value}, not confirmed")
    audit(db, "scan", scan.id, "status", "confirmed", "needs_review", grader_id)
    audit(db, "scan", scan.id, "is_counted", scan.is_counted, False, grader_id)
    scan.status, scan.is_counted = ScanStatus.needs_review, False
    if "reopened" not in (scan.flags or []):
        scan.flags = [*(scan.flags or []), "reopened"]
    db.flush()


def choose_counted(db: Session, event: Event, team_number: int, scan: Scan, grader_id: int) -> None:
    """Supervisor picks which of a team's scans counts; the others are discarded."""
    if scan.event_id != event.id or scan.team_number != team_number:
        raise ApiError(422, "wrong_scan", f"Scan #{scan.id} is not team {team_number}'s scan")
    if scan.mcq_score is None:
        raise ApiError(409, "unreadable", "That scan could not be read")
    others = db.scalars(
        select(Scan).where(
            Scan.event_id == event.id,
            Scan.team_number == team_number,
            Scan.id != scan.id,
            Scan.status != ScanStatus.discarded,
        )
    ).all()
    for other in others:
        discard(db, other, grader_id)
    db.flush()  # free the counted slot before taking it
    audit(db, "scan", scan.id, "status", scan.status.value, "confirmed", grader_id)
    audit(db, "scan", scan.id, "is_counted", scan.is_counted, True, grader_id)
    scan.status, scan.is_counted = ScanStatus.confirmed, True
    scan.flags = [f for f in scan.flags if f != "duplicate_team"]
    db.flush()


def rescore_event(db: Session, event: Event, grader_id: int) -> int:
    """Recompute every scan's score with the event's current answer key."""
    setup = setup_for(db, event)
    changed = 0
    for scan in db.scalars(select(Scan).where(Scan.event_id == event.id)):
        if not (scan.detected_marks or {}).get("questions"):
            continue
        new = rescore(scan, setup)
        if scan.mcq_score != new:
            audit(db, "scan", scan.id, "mcq_score", scan.mcq_score, new, grader_id)
            scan.mcq_score = new
            changed += 1
    return changed
