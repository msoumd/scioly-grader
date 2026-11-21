"""Ground truth for one fake (or hand-labelled real) sheet, saved as JSON beside the image."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class FillStyle(StrEnum):
    solid = "solid"  # dark pencil, fully filled
    light = "light"  # light pencil, 40-60% coverage
    partial = "partial"  # only part of the circle filled
    check = "check"  # a tick instead of a fill
    x = "x"  # a cross instead of a fill
    erased = "erased"  # faint smudge left after erasing: should read as BLANK


# Styles that mean "the student chose this bubble".
MARKING_STYLES = frozenset(
    {FillStyle.solid, FillStyle.light, FillStyle.partial, FillStyle.check, FillStyle.x}
)


def bubble_key(q: int, letter: str) -> str:
    return f"{q}:{letter}"


def team_key(column: int, digit: int) -> str:
    return f"T{column}:{digit}"


class SheetTruth(BaseModel):
    sample_id: str
    event_code: str
    sheet_version: int
    layout_version: int
    condition: str = "clean"  # photo condition, or "real" for hand-labelled photos
    seed: int | None = None

    # What the student meant: question -> letters chosen (empty list = left blank).
    marks: dict[int, list[str]]
    # Digits bubbled in each team-number column (normally exactly one each).
    team_marks: list[list[int]]
    # How each touched bubble was drawn, keyed "12:B" or "T0:7"; includes erased ones.
    fill_styles: dict[str, FillStyle] = Field(default_factory=dict)
    strays: int = 0  # small marks drawn outside any bubble
    # Page corners (top-left, top-right, bottom-right, bottom-left) in image pixels.
    page_corners: list[tuple[float, float]] | None = None
    augment: dict[str, Any] = Field(default_factory=dict)  # photo parameters used

    @property
    def team_number(self) -> int | None:
        """The team number, or None when the grid is ambiguous by design (a column left
        empty or with two digits); a correct reader should then flag it, not guess."""
        if not self.team_marks or any(len(col) != 1 for col in self.team_marks):
            return None
        return int("".join(str(col[0]) for col in self.team_marks))

    def marked(self, q: int) -> set[str]:
        return set(self.marks.get(q, ()))

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=1) + "\n")

    @classmethod
    def load(cls, path: Path) -> SheetTruth:
        return cls.model_validate_json(path.read_text())
