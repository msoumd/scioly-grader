"""Read uploads in the background so the upload request returns at once.

A small thread pool in the web process. If the server restarts mid-read, scans left in
``processing`` longer than ``stuck_after_seconds`` are picked up again on startup.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Scan, ScanStatus
from app.services.photos import delete_done_photos
from app.services.scans import process_scan
from app.services.storage import Storage

log = logging.getLogger("scioly.reading")


class ReadingQueue:
    def __init__(
        self, sessions: sessionmaker[Session], storage: Storage, settings: Settings
    ) -> None:
        self.sessions, self.storage, self.settings = sessions, storage, settings
        self.pool = (
            None
            if settings.reader_sync
            else ThreadPoolExecutor(
                max_workers=settings.reader_workers, thread_name_prefix="reader"
            )
        )
        self.futures: list[Future[None]] = []

    def _run(self, scan_id: int) -> None:
        try:
            with self.sessions() as db:
                process_scan(db, scan_id, self.storage)
                if self.settings.delete_photos_when_done:  # counted without review
                    delete_done_photos(db, self.storage, [scan_id])
        except Exception:  # pragma: no cover - process_scan already records failures
            log.exception("reading scan %s crashed", scan_id)

    def submit(self, scan_id: int) -> None:
        if self.pool is None:
            self._run(scan_id)
        else:
            self.futures.append(self.pool.submit(self._run, scan_id))
            self.futures = [f for f in self.futures if not f.done()]

    def wait(self) -> None:
        """Block until queued reads finish (tests, shutdown)."""
        for f in list(self.futures):
            f.result()

    def recover_stuck(self) -> int:
        """Re-queue scans stuck in processing (the server restarted mid-read)."""
        cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.stuck_after_seconds)
        with self.sessions() as db:
            stuck = [
                s.id
                for s in db.scalars(select(Scan).where(Scan.status == ScanStatus.processing))
                if _aware(s.updated_at) <= cutoff
            ]
        for scan_id in stuck:
            log.warning("retrying scan %s left in processing", scan_id)
            self.submit(scan_id)
        return len(stuck)

    def sweep_photos(self) -> int:
        """Delete photos of counted/discarded scans that an earlier attempt missed."""
        if not self.settings.delete_photos_when_done:
            return 0
        with self.sessions() as db:
            return delete_done_photos(db, self.storage)

    def shutdown(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=True)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
