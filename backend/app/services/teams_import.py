"""Import the one-time Teams CSV (``team_number,team_name``) and upsert by team number."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Event, Team
from app.schemas.event_setup import TeamRow
from app.services.event_import import describe_error

REQUIRED_COLUMNS = ("team_number", "team_name")


@dataclass
class TeamsReport:
    source: str
    teams: list[TeamRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.teams)

    def to_text(self) -> str:
        lines = [f"Teams import: {self.source}"]
        if self.ok:
            lines.append(f"Result: OK - {len(self.teams)} teams")
        else:
            n = len(self.errors)
            lines.append(f"Result: FAILED - {n} problem{'s' if n != 1 else ''} to fix")
        for title, items in (("Warnings", self.warnings), ("Problems", self.errors)):
            if items:
                lines.append(f"{title}:")
                lines += [f"  - {item}" for item in items]
        return "\n".join(lines)


def _decode(data: bytes, report: TeamsReport) -> str | None:
    try:
        return data.decode("utf-8-sig")  # strips Excel's BOM if present
    except UnicodeDecodeError:
        report.errors.append("File is not UTF-8 text. In Excel use File > Save As > 'CSV UTF-8'.")
        return None


def parse_teams_csv(data: bytes, source: str = "teams.csv") -> TeamsReport:
    """Validate the CSV. Collects every problem; never raises for bad content."""
    report = TeamsReport(source=source)
    text = _decode(data, report)
    if text is None:
        return report

    reader = csv.reader(io.StringIO(text, newline=""))
    header_row = next(reader, None)
    header = [h.strip().lower() for h in header_row or []]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        report.errors.append(
            f"Line 1: header must contain {','.join(REQUIRED_COLUMNS)} "
            f"(missing {', '.join(missing)})"
        )
        return report
    extra = [h for h in header if h and h not in REQUIRED_COLUMNS]
    if extra:
        report.warnings.append(f"Line 1: extra column(s) ignored: {', '.join(extra)}")
    i_num, i_name = header.index("team_number"), header.index("team_name")

    seen: dict[int, int] = {}
    for row in reader:
        line = reader.line_num
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        raw_num = cells[i_num] if i_num < len(cells) else ""
        name = cells[i_name] if i_name < len(cells) else ""
        if not raw_num.lstrip("-").isdigit():
            shown = repr(raw_num) if raw_num else "blank"
            report.errors.append(f"Line {line}: team_number must be a whole number (got {shown})")
            continue
        try:
            team = TeamRow(team_number=int(raw_num), team_name=name)
        except ValidationError as exc:
            report.errors += [f"Line {line}: {describe_error(e)}" for e in exc.errors()]
            continue
        if team.team_number in seen:
            report.errors.append(
                f"Line {line}: team_number {team.team_number} is already used on line "
                f"{seen[team.team_number]}"
            )
            continue
        seen[team.team_number] = line
        report.teams.append(team)

    if not report.teams and not report.errors:
        report.errors.append("No teams found below the header")
    return report


def import_teams_csv(path: str | Path) -> TeamsReport:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return TeamsReport(source=path.name, errors=[f"Could not read {path.name} ({exc})"])
    return parse_teams_csv(data, path.name)


@dataclass(frozen=True)
class TeamsSaveResult:
    inserted: int
    updated: int
    warnings: list[str]

    def to_text(self) -> str:
        lines = [f"Saved teams: {self.inserted} new, {self.updated} updated"]
        lines += [f"  - warning: {w}" for w in self.warnings]
        return "\n".join(lines)


def save_teams(session: Session, teams: list[TeamRow]) -> TeamsSaveResult:
    """Insert new team numbers, rename existing ones. The caller commits."""
    max_digits = session.scalar(select(func.max(Event.team_number_digits)))
    warnings = []
    if max_digits:
        limit = 10**max_digits - 1
        warnings = [
            f"team {t.team_number} needs more than {max_digits} digits; no event's "
            f"team-number grid can record it (largest is {max_digits} digits)"
            for t in teams
            if t.team_number > limit
        ]

    existing = {
        t.team_number: t
        for t in session.scalars(
            select(Team).where(Team.team_number.in_([t.team_number for t in teams]))
        )
    }
    inserted = updated = 0
    for row in teams:
        team = existing.get(row.team_number)
        if team is None:
            session.add(Team(team_number=row.team_number, name=row.team_name))
            inserted += 1
        elif team.name != row.team_name:
            team.name = row.team_name
            updated += 1
    session.flush()
    return TeamsSaveResult(inserted=inserted, updated=updated, warnings=warnings)
