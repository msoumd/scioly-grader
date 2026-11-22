"""Photos are kept only while a person might need to look at them.

Once a sheet is counted or discarded, its photos are deleted: the original upload, the
straightened page, and the crops of the team number and flagged questions. The marks,
score, corrections and audit history stay, so results, CSV and re-scoring are unaffected;
the paper sheet is the record if anyone wants to look again. This keeps storage tiny (only
sheets waiting for review), which fits Supabase's free plan.

A PDF's pages share one original file, which is deleted only when every page from it is
counted or discarded. Deleting is best effort: if storage is unreachable the scan keeps
``photos_deleted = False`` and the next sweep (after another action or at startup) retries.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Scan, ScanStatus
from app.services.storage import Storage

log = logging.getLogger("scioly")

DONE = (ScanStatus.confirmed, ScanStatus.discarded)


def _derived_keys(scan: Scan) -> list[str]:
    """Straightened page and crops made from this scan."""
    detected: dict[str, Any] = scan.detected_marks or {}
    keys = [scan.warped_path] if scan.warped_path else []
    team = detected.get("team") or {}
    if team.get("crop"):
        keys.append(team["crop"])
    keys += [q["crop"] for q in (detected.get("questions") or {}).values() if q.get("crop")]
    return keys


def _without_crops(detected: dict[str, Any]) -> dict[str, Any]:
    out = dict(detected)
    if "team" in out:
        out["team"] = {k: v for k, v in (out["team"] or {}).items() if k != "crop"}
    if "questions" in out:
        out["questions"] = {
            q: {k: v for k, v in info.items() if k != "crop"}
            for q, info in (out["questions"] or {}).items()
        }
    return out


def delete_done_photos(db: Session, storage: Storage, scan_ids: Iterable[int] | None = None) -> int:
    """Delete the photos of counted/discarded scans (these ids, or all). Commits.
    Returns how many scans were cleaned."""
    query = select(Scan).where(Scan.status.in_(DONE), Scan.photos_deleted.is_(False))
    if scan_ids is not None:
        ids = list(scan_ids)
        if not ids:
            return 0
        query = query.where(Scan.id.in_(ids))
    cleaned = 0
    for scan in db.scalars(query).all():
        keys = _derived_keys(scan)
        still_needed = db.scalar(
            select(Scan.id).where(
                Scan.image_path == scan.image_path, Scan.id != scan.id, Scan.status.not_in(DONE)
            )
        )
        if still_needed is None:  # no other page of this upload still needs the original
            keys.append(scan.image_path)
        try:
            storage.delete(keys)
        except Exception:  # storage down: leave it for the next sweep
            log.exception("could not delete photos of scan %s; will retry", scan.id)
            continue
        scan.photos_deleted = True
        scan.warped_path = None
        scan.detected_marks = _without_crops(scan.detected_marks or {})
        cleaned += 1
    db.commit()
    return cleaned
