"""Build a labelled dataset of fake phone photos for one event, reproducibly from a seed.

Layout on disk::

    out/manifest.json     event setup, seed, conditions, counts (enough to rebuild it)
    out/0000.jpg          fake photo
    out/0000.json         SheetTruth: what the student meant + how it was photographed
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.harness.answers import generate_answers
from app.harness.augment import CONDITIONS, DEFAULT_SIZE, photograph
from app.harness.painter import paint_sheet
from app.harness.truth import SheetTruth
from app.schemas.event_setup import EventSetup
from app.services.layout import build_layout
from app.services.sheet_pdf import render_sheet_image

MANIFEST = "manifest.json"
DATASET_FORMAT = 1
_SAMPLE_FILE = re.compile(r"^\d{4,}\.(jpg|json)$")


def resolve_conditions(spec: str) -> list[str]:
    """``"all"`` or a comma list like ``"clean,shadow"``."""
    if spec.strip().lower() == "all":
        return list(CONDITIONS)
    names = [c.strip() for c in spec.split(",") if c.strip()]
    unknown = [c for c in names if c not in CONDITIONS]
    if unknown or not names:
        raise ValueError(
            f"unknown condition(s) {', '.join(unknown) or '(none given)'}; "
            f"choose 'all' or from: {', '.join(CONDITIONS)}"
        )
    return names


def _clear_old_samples(out: Path) -> None:
    for f in out.iterdir():
        if f.is_file() and (_SAMPLE_FILE.match(f.name) or f.name == MANIFEST):
            f.unlink()


def build_dataset(
    setup: EventSetup,
    out: Path,
    n: int,
    conditions: Sequence[str] = CONDITIONS,
    seed: int = 0,
    dpi: int = 200,
    size: tuple[int, int] = DEFAULT_SIZE,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Write ``n`` samples, cycling through ``conditions``. Sample ``i`` depends only on
    (seed, i), so a dataset can be rebuilt byte-for-byte or extended."""
    if n < 1:
        raise ValueError("n must be at least 1")
    out.mkdir(parents=True, exist_ok=True)
    _clear_old_samples(out)

    layout = build_layout(setup)
    page = render_sheet_image(layout, dpi)
    width = max(4, len(str(n - 1)))
    counts: Counter[str] = Counter()
    profiles: Counter[str] = Counter()
    ids = []

    for i in range(n):
        sample_id = str(i).zfill(width)
        condition = conditions[i % len(conditions)]
        rng = np.random.default_rng([seed, i])
        answers = generate_answers(setup, rng)
        truth = SheetTruth(
            sample_id=sample_id,
            event_code=layout.event_id,
            sheet_version=layout.sheet_version,
            layout_version=layout.layout_version,
            condition=condition,
            seed=seed,
            profile=answers.profile,
            marks=answers.marks,
            team_marks=answers.team_marks,
            fill_styles=answers.fill_styles,
            strays=answers.strays,
        )
        painted = paint_sheet(page, layout, truth, dpi, rng)
        photo = photograph(painted, condition, rng, size=size)
        truth = truth.model_copy(update={"page_corners": photo.corners, "augment": photo.params})
        (out / f"{sample_id}.jpg").write_bytes(photo.jpeg)
        truth.save(out / f"{sample_id}.json")
        counts[condition] += 1
        profiles[answers.profile] += 1
        ids.append(sample_id)
        if progress:
            progress(i + 1, n)

    manifest: dict[str, Any] = {
        "format": DATASET_FORMAT,
        "kind": "synthetic",
        "event_id": layout.event_id,
        "sheet_version": layout.sheet_version,
        "layout_version": layout.layout_version,
        "n": n,
        "seed": seed,
        "dpi": dpi,
        "size": list(size),
        "conditions": list(conditions),
        "counts": dict(sorted(counts.items())),
        "profiles": dict(sorted(profiles.items())),
        "samples": ids,
        "setup": setup.model_dump(mode="json"),
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def write_contact_sheet(dataset: Path, out: Path, count: int = 20, cols: int = 5,
                        thumb: tuple[int, int] = (300, 400)) -> int:  # fmt: skip
    """Tile thumbnails (one per condition first, then the rest) into one labelled JPEG.
    Returns how many images were used."""
    truths = sorted(
        (SheetTruth.load(p) for p in dataset.glob("*.json") if _SAMPLE_FILE.match(p.name)),
        key=lambda t: t.sample_id,
    )
    first: dict[str, SheetTruth] = {}
    for t in truths:
        first.setdefault(t.condition, t)
    rest = [t for t in truths if first[t.condition] is not t]
    chosen = (list(first.values()) + rest)[:count]
    if not chosen:
        raise ValueError(f"no samples found in {dataset}")
    tiles = []
    for t in chosen:
        img = cv2.imread(str(dataset / f"{t.sample_id}.jpg"), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"missing or unreadable image for sample {t.sample_id}")
        tile = cv2.resize(img, thumb, interpolation=cv2.INTER_AREA)
        label = f"{t.sample_id} {t.condition}"
        cv2.rectangle(tile, (0, 0), (thumb[0], 26), (255, 255, 255), -1)
        cv2.putText(tile, label, (5, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 200), 1,
                    cv2.LINE_AA)  # fmt: skip
        tiles.append(tile)
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 255))
    grid = np.vstack([np.hstack(tiles[i : i + cols]) for i in range(0, len(tiles), cols)])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), grid, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return len(chosen)
