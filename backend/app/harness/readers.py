"""Reference readers for checking the evaluator itself. Phase 4 adds the real detector."""

from __future__ import annotations

from app.harness.evaluate import Reader, Sample
from app.schemas.sheet_read import SheetRead


def oracle_reader(sample: Sample) -> SheetRead:
    """Returns the truth: must score 100%. Ambiguous team grids are flagged, not guessed."""
    t = sample.truth
    return SheetRead(
        event_code=t.event_code,
        sheet_version=t.sheet_version,
        team_number=t.team_number,
        team_flagged=t.team_number is None,
        marks={q: list(v) for q, v in t.marks.items() if v},
    )


def blank_reader(sample: Sample) -> SheetRead:
    """Sees nothing and flags nothing: every answered question is a silent error."""
    return SheetRead()


READERS: dict[str, Reader] = {"oracle": oracle_reader, "blank": blank_reader}
