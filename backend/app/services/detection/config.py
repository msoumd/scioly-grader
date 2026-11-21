"""Every detection threshold in one place. Values were chosen by running the phase 3
harness (see docs/DECISIONS.md, "Detection thresholds"); change them only with a new
evaluation run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionConfig:
    # --- loading
    max_long_edge: int = 2500  # photos are downscaled to this before anything else
    pdf_dpi: int = 200

    # --- page
    dpi: int = 200  # canonical warped page resolution
    min_markers: int = 3  # with 3 of 4 the page is still read, but flagged

    # --- bubble measurement
    align_search_frac: float = 0.35  # row re-centring search, as a fraction of bubble spacing
    inner_ratio: float = 0.72  # measure fill inside this fraction of the bubble radius
    background_kernel_frac: float = 0.025  # illumination estimate window, fraction of width

    # --- decisions, on fill relative to the page's own solid-mark level (0..1+)
    mark_threshold: float = 0.22  # at or above: marked
    blank_threshold: float = 0.15  # below: blank; in between: ambiguous -> human review
    min_mark_level: float = 0.25  # floor for the page's solid-mark level (absolute fill)
    erasure_ratio: float = 2.5  # two marks, one this many times darker: possible erasure

    # --- team number
    team_mark_threshold: float = 0.22
    team_blank_threshold: float = 0.15


DEFAULT_CONFIG = DetectionConfig()
