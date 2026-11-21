"""Validated shape of a supervisor's event-setup spreadsheet (Event + Questions tabs)
and the one-time Teams CSV. The spreadsheet reader (build step 1) turns rows into these;
validation errors here become the import report's problem messages."""

from __future__ import annotations

import datetime as dt
import string
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import ScoringMode

LETTERS = string.ascii_uppercase[:9]  # A..I — at most 9 bubbles per question

Points = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
NonNegPoints = Annotated[Decimal, Field(ge=0, max_digits=6, decimal_places=2)]


class QuestionSetup(BaseModel):
    model_config = ConfigDict(frozen=True)

    q: int = Field(ge=1)
    points: Points
    options: int = Field(ge=2, le=9)
    correct: tuple[str, ...] = Field(min_length=1)
    scoring: ScoringMode = ScoringMode.exact
    penalty_per_wrong: NonNegPoints = Decimal("0")

    @field_validator("correct", mode="before")
    @classmethod
    def _split_letters(cls, v: object) -> object:
        """Accept "A, c" / "AC" / ["A","C"]; normalise to sorted unique uppercase letters."""
        if isinstance(v, str):
            raw = v.replace(",", " ").split()
            letters = [ch for tok in raw for ch in tok] if all(len(t) > 1 for t in raw) else raw
        else:
            letters = list(v)  # type: ignore[call-overload]
        return tuple(sorted({str(x).strip().upper() for x in letters if str(x).strip()}))

    @model_validator(mode="after")
    def _letters_within_options(self) -> Self:
        allowed = LETTERS[: self.options]
        bad = [c for c in self.correct if c not in allowed]
        if bad:
            raise ValueError(
                f"question {self.q}: correct answer {','.join(bad)} is beyond the "
                f"{self.options} options (A-{allowed[-1]})"
            )
        if self.scoring is ScoringMode.exact and self.penalty_per_wrong:
            raise ValueError(f"question {self.q}: penalty_per_wrong only applies to 'partial'")
        return self

    @property
    def correct_csv(self) -> str:
        return ",".join(self.correct)


class EventInfo(BaseModel):
    event_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    event_name: str = Field(min_length=1, max_length=200)
    tournament: str = Field(min_length=1, max_length=200)
    date: dt.date | None = None
    sheet_version: int = Field(default=1, ge=1)
    team_number_digits: int = Field(ge=1, le=4)
    total_points: NonNegPoints
    free_response_max: NonNegPoints


class EventSetup(BaseModel):
    event: EventInfo
    questions: list[QuestionSetup] = Field(min_length=1)

    @property
    def mcq_points_total(self) -> Decimal:
        return sum((q.points for q in self.questions), Decimal("0"))

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        nums = [q.q for q in self.questions]
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate question numbers: {dupes}")
        expected = self.event.free_response_max + self.mcq_points_total
        if self.event.total_points != expected:
            raise ValueError(
                f"total_points is {self.event.total_points} but free_response_max "
                f"({self.event.free_response_max}) + multiple-choice points "
                f"({self.mcq_points_total}) = {expected}"
            )
        return self


class TeamRow(BaseModel):
    team_number: int = Field(ge=0)
    team_name: str = Field(min_length=1, max_length=200)
