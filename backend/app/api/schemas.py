"""Request and response shapes for the HTTP API (shown on /docs)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import ScanStatus


class ImportReportOut(BaseModel):
    ok: bool
    source: str
    errors: list[str]
    warnings: list[str]
    notes: list[str]
    tabs_ignored: list[str]
    question_count: int
    mcq_points_total: Decimal
    sheet_note: str | None
    text: str  # the same report as the command line prints


class EventImportOut(BaseModel):
    report: ImportReportOut
    saved: bool
    action: str | None = None  # created | replaced | new_version
    event_code: str | None = None


class QuestionOut(BaseModel):
    q: int
    points: Decimal
    options: int
    correct: list[str]
    scoring: str
    penalty_per_wrong: Decimal


class EventOut(BaseModel):
    code: str
    name: str
    tournament: str
    date: date | None
    sheet_version: int
    team_number_digits: int
    total_points: Decimal
    free_response_max: Decimal
    mcq_points_total: Decimal
    question_count: int
    scans_needing_review: int = 0
    scans_counted: int = 0


class EventDetailOut(EventOut):
    questions: list[QuestionOut]


class TeamsImportOut(BaseModel):
    ok: bool
    errors: list[str]
    warnings: list[str]
    inserted: int = 0
    updated: int = 0
    text: str
    saved: bool = False


class TeamOut(BaseModel):
    team_number: int
    name: str


class ScanCreated(BaseModel):
    id: int
    page: int
    status: ScanStatus


class UploadOut(BaseModel):
    scans: list[ScanCreated]


class QuestionReadOut(BaseModel):
    q: int
    marked: list[str]  # after corrections
    detected: list[str]  # what the reader saw
    corrected: bool
    fills: dict[str, float]
    confidence: float | None
    flags: list[str]
    crop_url: str | None


class ScanOut(BaseModel):
    id: int
    event_code: str
    status: ScanStatus
    is_counted: bool
    team_number: int | None
    mcq_score: Decimal | None
    flags: list[str]
    page: int
    error: str | None
    grader: str
    created_at: datetime
    updated_at: datetime
    original_url: str | None  # None once the photos were deleted
    warped_url: str | None
    photos_deleted: bool = False
    page_flags: list[str] = []
    team: dict[str, Any] = {}
    team_crop_url: str | None = None
    discard_reason: str | None = None
    questions: list[QuestionReadOut] = []


class ScanSummary(BaseModel):
    id: int
    status: ScanStatus
    is_counted: bool
    team_number: int | None
    mcq_score: Decimal | None
    flags: list[str]
    grader: str
    updated_at: datetime


class CorrectionIn(BaseModel):
    marks: dict[int, list[str]] | None = Field(
        default=None, description='Letters marked per question, e.g. {"12": ["B"]}; [] = blank'
    )
    team_number: int | None = Field(default=None, description="Set or fix the team number")


class ConfirmIn(BaseModel):
    accept_unknown_team: bool = Field(
        default=False,
        description="Count it even though the team number is not on the teams list",
    )


class DiscardIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200, description="Why, for the record")


class CountedScanIn(BaseModel):
    scan_id: int


class DuplicateOut(BaseModel):
    team_number: int
    team_name: str | None
    scans: list[ScanSummary]


class FreeResponseIn(BaseModel):
    value: Decimal = Field(ge=0, description="Total free-response points, in 0.5 steps")


class FreeResponseOut(BaseModel):
    team_number: int
    value: Decimal
    grader: str
    updated_at: datetime


class ResultRow(BaseModel):
    rank: int | None
    team_number: int
    team_name: str
    mcq: Decimal | None
    free_response: Decimal | None
    total: Decimal | None  # only once both parts are in
    missing: list[str]  # "multiple_choice", "free_response", "review" (scan waiting)
    scan_id: int | None = None  # the counted scan
    free_response_id: int | None = None
    mcq_by: str | None
    mcq_at: datetime | None
    free_response_by: str | None
    free_response_at: datetime | None


class ResultsOut(BaseModel):
    event_code: str
    total_points: Decimal
    rows: list[ResultRow]
    teams_complete: int
    teams_missing_something: int
    teams_without_scan: int
    teams_without_free_response: int
    scans_needing_review: int


class RescoreOut(BaseModel):
    changed: int
    saved: bool = True


class AuditOut(BaseModel):
    id: int
    entity: str
    entity_id: int
    field: str
    old_value: str | None
    new_value: str | None
    grader: str
    created_at: datetime
