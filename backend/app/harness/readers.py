"""Readers the evaluator can measure. Each entry makes a reader for one event's setup.

- ``oracle``: returns the truth; must score 100% (checks the evaluator itself).
- ``blank``: sees nothing; every answered question is a silent error.
- ``detector``: the real reading pipeline (phase 4).
"""

from __future__ import annotations

from collections.abc import Callable

from app.harness.evaluate import Reader, Sample
from app.schemas.event_setup import EventSetup
from app.schemas.sheet_read import SheetRead

ReaderFactory = Callable[[EventSetup], Reader]


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


def detector_reader(setup: EventSetup) -> Reader:
    """The real pipeline. The event comes from the QR code; if the QR cannot be read, the
    dataset's event is used, as a grader would pick it by hand (QR misses are still
    counted in the report's 'QR read' column)."""
    from app.services.detection import read_sheet

    def lookup(code: str, version: int) -> EventSetup | None:
        ev = setup.event
        return setup if (code, version) == (ev.event_id, ev.sheet_version) else None

    def read(sample: Sample) -> SheetRead:
        return read_sheet(sample.load_image(), lookup, fallback=setup).to_read()

    return read


READERS: dict[str, ReaderFactory] = {
    "oracle": lambda _setup: oracle_reader,
    "blank": lambda _setup: blank_reader,
    "detector": detector_reader,
}
