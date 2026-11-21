"""What reading one photographed sheet produces. The detector (phase 4) returns this;
the test harness compares it against the known truth."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SheetRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_code: str | None = None  # from the QR code; None if it could not be read
    sheet_version: int | None = None
    team_number: int | None = None  # None if the team grid could not be read
    team_flagged: bool = False  # team number needs a human to check
    # Letters read as marked per question; a missing question means "nothing marked".
    marks: dict[int, list[str]] = Field(default_factory=dict)
    # Questions sent to human review (ambiguous, light, double marks, ...).
    flagged: list[int] = Field(default_factory=list)

    def marked(self, q: int) -> set[str]:
        return set(self.marks.get(q, ()))
