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
    first_row_search_frac: float = 0.45  # wider for the top row of each column (< 0.5)
    inner_ratio: float = 0.80  # measure fill inside this fraction of the bubble radius
    background_kernel_frac: float = 0.025  # illumination estimate window, fraction of width

    # --- decisions, on fill relative to the page's own solid-mark level (0..1+)
    mark_threshold: float = 0.22  # at or above: marked
    blank_threshold: float = 0.15  # below: blank; in between: ambiguous -> human review
    min_mark_level: float = 0.25  # floor for the page's solid-mark level (absolute fill)
    erasure_ratio: float = 2.5  # two+ marks, one this many times darker: possible erasure
    coverage_cut: float = 0.5  # 'real pencil' = darker than this share of the solid level
    coverage_smooth_px: float = 1.2  # blur before measuring coverage, so noise is not pencil
    letter_ink_margin: float = 0.06  # how much darker one printed letter may be than another
    low_contrast_frac: float = 0.70  # row outlines fainter than this share of the page's: review

    # --- blurry photos: read conservatively (wider "ask a human" band)
    blurry_sharpness: float = 0.45  # median printed-ring edge strength below this = blurry
    blurry_mark_threshold: float = 0.60
    blurry_blank_threshold: float = 0.06

    # --- team number
    team_mark_threshold: float = 0.22
    team_blank_threshold: float = 0.15


DEFAULT_CONFIG = DetectionConfig()
