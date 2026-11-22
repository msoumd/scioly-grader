"""Results table: multiple choice (counted scan) + free response per team, ranked.

- A team's total exists only once **both** parts are in; until then it shows what is
  missing and has no rank, so a half-entered team can't look like it is winning or losing.
- Ranking: total descending; ties share a rank (1, 2, 2, 4). No tiebreakers in v1.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Event, FreeResponseScore, Grader, Scan, ScanStatus, Team
from app.services.scoring import fmt_points

CSV_COLUMNS = [
    "rank",
    "team_number",
    "team_name",
    "multiple_choice",
    "free_response",
    "total",
    "missing",
    "multiple_choice_by",
    "multiple_choice_at",
    "free_response_by",
    "free_response_at",
]


@dataclass
class Row:
    team_number: int
    team_name: str
    mcq: Decimal | None
    free_response: Decimal | None
    mcq_by: str | None
    mcq_at: datetime | None
    fr_by: str | None
    fr_at: datetime | None
    waiting_review: bool
    scan_id: int | None = None
    free_response_id: int | None = None
    rank: int | None = None

    @property
    def total(self) -> Decimal | None:
        if self.mcq is None or self.free_response is None:
            return None
        return self.mcq + self.free_response

    @property
    def missing(self) -> list[str]:
        out = []
        if self.mcq is None:
            out.append("multiple_choice")
        if self.free_response is None:
            out.append("free_response")
        if self.waiting_review:
            out.append("review")
        return out


def rank(rows: list[Row]) -> None:
    complete = [r for r in rows if r.total is not None]
    scored = sorted(complete, key=lambda r: r.total or Decimal(0), reverse=True)
    prev_total: Decimal | None = None
    prev_rank = 0
    for i, r in enumerate(scored, start=1):
        if r.total != prev_total:
            prev_total, prev_rank = r.total, i
        r.rank = prev_rank
    for r in rows:
        if r.total is None:
            r.rank = None


def results(db: Session, event: Event) -> list[Row]:
    names = dict(db.execute(select(Grader.id, Grader.name)).all())
    counted = {
        s.team_number: s
        for s in db.scalars(select(Scan).where(Scan.event_id == event.id, Scan.is_counted))
    }
    waiting = set(
        db.scalars(
            select(Scan.team_number).where(
                Scan.event_id == event.id,
                Scan.status.in_([ScanStatus.needs_review, ScanStatus.processing]),
            )
        )
    )
    fr = {
        f.team_number: f
        for f in db.scalars(select(FreeResponseScore).where(FreeResponseScore.event_id == event.id))
    }
    rows = []
    for team in db.scalars(select(Team).order_by(Team.team_number)):
        scan, free = counted.get(team.team_number), fr.get(team.team_number)
        rows.append(
            Row(
                team_number=team.team_number,
                team_name=team.name,
                mcq=scan.mcq_score if scan else None,
                free_response=Decimal(free.value) if free else None,
                mcq_by=names.get(scan.grader_id) if scan else None,
                mcq_at=scan.updated_at if scan else None,
                fr_by=names.get(free.grader_id) if free else None,
                fr_at=free.updated_at if free else None,
                waiting_review=team.team_number in waiting and scan is None,
                scan_id=scan.id if scan else None,
                free_response_id=free.id if free else None,
            )
        )
    rank(rows)
    rows.sort(key=lambda r: (r.rank is None, r.rank or 0, r.team_number))
    return rows


def pending_reviews(db: Session, event: Event) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Scan)
            .where(Scan.event_id == event.id, Scan.status == ScanStatus.needs_review)
        )
        or 0
    )


def _when(t: datetime | None) -> str:
    """UTC, to the second, e.g. 2026-11-21T14:03:05Z (SQLite gives naive UTC times)."""
    if t is None:
        return ""
    t = t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def results_csv(rows: list[Row]) -> str:
    """The results table as CSV, starting with a UTF-8 byte-order mark so Excel reads
    team names with accents correctly."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        w.writerow(
            [
                r.rank or "",
                r.team_number,
                r.team_name,
                fmt_points(r.mcq) if r.mcq is not None else "",
                fmt_points(r.free_response) if r.free_response is not None else "",
                fmt_points(r.total) if r.total is not None else "",
                " ".join(r.missing),
                r.mcq_by or "",
                _when(r.mcq_at),
                r.fr_by or "",
                _when(r.fr_at),
            ]
        )
    return buf.getvalue()
