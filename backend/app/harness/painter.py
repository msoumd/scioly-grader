"""Draw pencil marks onto a clean rendered sheet at the layout's bubble positions.

Marks are grainy grey strokes, not perfect black discs, so detection is tested on
something that looks like graphite. Works on a greyscale page image rendered at ``dpi``.
"""

from __future__ import annotations

import cv2
import numpy as np
import numpy.typing as npt

from app.harness.truth import FillStyle, SheetTruth
from app.services.layout import Bubble, SheetLayout

Image = npt.NDArray[np.uint8]
Mask = npt.NDArray[np.float32]


def bubble_for_key(layout: SheetLayout, key: str) -> Bubble:
    """``"12:B"`` -> question 12's B bubble; ``"T1:7"`` -> team column 1, digit 7."""
    where, label = key.split(":")
    if where.startswith("T"):
        return layout.team_grid.columns[int(where[1:])][int(label)]
    q = int(where)
    row = next(r for r in layout.questions if r.q == q)
    return next(b for b in row.bubbles if b.label == label)


def _blend(
    img: Image, mask: Mask, x0: int, y0: int, darkness: float, opacity: float,
    rng: np.random.Generator,
) -> None:  # fmt: skip
    """Darken ``img`` where ``mask`` > 0 with grainy graphite of the given darkness."""
    h, w = mask.shape
    y1, x1 = min(y0 + h, img.shape[0]), min(x0 + w, img.shape[1])
    if x0 < 0 or y0 < 0 or y1 <= y0 or x1 <= x0:
        return
    mask = mask[: y1 - y0, : x1 - x0]
    roi = img[y0:y1, x0:x1].astype(np.float32)
    grain = rng.normal(0, 22, mask.shape).astype(np.float32)
    grain = np.asarray(cv2.GaussianBlur(grain, (0, 0), 0.7), np.float32)
    tone = np.clip(darkness + grain, 0, 255)
    alpha = np.clip(mask * opacity * (0.85 + 0.15 * rng.random(mask.shape)), 0, 1)
    out = np.minimum(roi, roi * (1 - alpha) + tone * alpha)
    img[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)


def _canvas(rr: float) -> tuple[Mask, float]:
    size = int(np.ceil(rr * 3)) * 2 + 1
    return np.zeros((size, size), np.float32), size / 2


def _soften(mask: Mask) -> Mask:
    return np.asarray(cv2.GaussianBlur(mask, (0, 0), 0.6), np.float32)


def _circle(rr: float, rng: np.random.Generator, scale: tuple[float, float]) -> Mask:
    mask, c = _canvas(rr)
    jx, jy = rng.normal(0, rr * 0.06, 2)
    axes = (rr * rng.uniform(*scale), rr * rng.uniform(*scale))
    cv2.ellipse(mask, (int(c + jx), int(c + jy)), (int(axes[0]), int(axes[1])),
                float(rng.uniform(0, 180)), 0, 360, 1.0, -1)  # fmt: skip
    return mask


def _strokes(rr: float, rng: np.random.Generator, count: int, width: float) -> Mask:
    """Parallel-ish scribble lines across the bubble, clipped to it."""
    mask, c = _canvas(rr)
    angle = rng.uniform(0, np.pi)
    dx, dy = np.cos(angle), np.sin(angle)
    for k in range(count):
        offset = (k - (count - 1) / 2) * rr * 1.6 / max(count, 1) + rng.normal(0, rr * 0.08)
        ox, oy = -dy * offset, dx * offset
        p1 = (int(c + ox - dx * rr), int(c + oy - dy * rr))
        p2 = (int(c + ox + dx * rr), int(c + oy + dy * rr))
        cv2.line(mask, p1, p2, 1.0, max(1, int(width)))
    clip, _ = _canvas(rr)
    cv2.circle(clip, (int(c), int(c)), int(rr), 1.0, -1)
    return mask * clip


def _partial(rr: float, rng: np.random.Generator) -> Mask:
    circle = _circle(rr, rng, (0.85, 0.98))
    _, c = _canvas(rr)
    yy, xx = np.mgrid[0 : circle.shape[0], 0 : circle.shape[1]].astype(np.float32)
    angle = rng.uniform(0, 2 * np.pi)
    cut = rng.uniform(-0.3, 0.3) * rr  # keeps roughly 35-65% of the circle
    keep = ((xx - c) * np.cos(angle) + (yy - c) * np.sin(angle)) < cut
    return (circle * keep).astype(np.float32)


def _check(rr: float, rng: np.random.Generator) -> Mask:
    mask, c = _canvas(rr)
    s = rr * rng.uniform(0.95, 1.2)
    pts = np.array([[-0.6, 0.0], [-0.1, 0.5], [0.7, -0.7]]) * s + c
    pts += rng.normal(0, rr * 0.05, pts.shape)
    cv2.polylines(mask, [pts.astype(np.int32)], False, 1.0, max(2, int(rr * 0.3)))
    return mask


def _cross(rr: float, rng: np.random.Generator) -> Mask:
    mask, c = _canvas(rr)
    s = rr * rng.uniform(0.7, 0.95)
    for sign in (1, -1):
        p1 = (int(c - s), int(c - sign * s))
        p2 = (int(c + s), int(c + sign * s))
        cv2.line(mask, p1, p2, 1.0, max(2, int(rr * 0.27)))
    return mask


def paint_mark(img: Image, cx: float, cy: float, rr: float, style: FillStyle,
               rng: np.random.Generator) -> None:  # fmt: skip
    """Draw one mark centred at pixel (cx, cy) on a bubble of pixel radius rr."""
    if style is FillStyle.solid:
        mask = _circle(rr, rng, (0.88, 1.02))
        darkness, opacity = rng.uniform(30, 80), rng.uniform(0.85, 1.0)
    elif style is FillStyle.light:
        mask = _strokes(rr, rng, int(rng.integers(3, 6)), rr * 0.35)
        darkness, opacity = rng.uniform(105, 150), rng.uniform(0.65, 0.85)
    elif style is FillStyle.partial:
        mask = _partial(rr, rng)
        darkness, opacity = rng.uniform(35, 85), rng.uniform(0.85, 1.0)
    elif style is FillStyle.check:
        mask = _check(rr, rng)
        darkness, opacity = rng.uniform(30, 70), 0.95
    elif style is FillStyle.x:
        mask = _cross(rr, rng)
        darkness, opacity = rng.uniform(30, 70), 0.95
    else:  # erased: faint smudge plus a few ghost strokes
        mask = np.maximum(_circle(rr, rng, (0.8, 1.0)) * 0.6,
                          _strokes(rr, rng, 3, rr * 0.3) * 0.9)  # fmt: skip
        darkness, opacity = rng.uniform(185, 215), rng.uniform(0.45, 0.65)
    mask = _soften(mask)
    half = mask.shape[0] // 2
    _blend(img, mask, int(round(cx)) - half, int(round(cy)) - half, darkness, opacity, rng)


def _paint_strays(img: Image, layout: SheetLayout, count: int, scale: float,
                  rng: np.random.Generator) -> None:  # fmt: skip
    """Small pencil marks in the question area, never on or touching a bubble."""
    if count == 0 or not layout.questions:
        return
    centres = np.array([(b.cx, b.cy) for row in layout.questions for b in row.bubbles])
    r = layout.bubble_r
    xs = [row.label_box.x for row in layout.questions]
    ys = [row.label_box.y for row in layout.questions]
    x_lo, x_hi = min(xs), max(row.bubbles[-1].cx + r for row in layout.questions)
    y_lo, y_hi = min(ys), max(row.label_box.bottom for row in layout.questions)
    placed = attempts = 0
    while placed < count and attempts < 200:
        attempts += 1
        x, y = rng.uniform(x_lo, x_hi), rng.uniform(y_lo, y_hi)
        if np.min(np.hypot(centres[:, 0] - x, centres[:, 1] - y)) < r * 2.2:
            continue
        rr = r * scale * rng.uniform(0.3, 0.6)
        mask, c = _canvas(rr * 2)
        angle = rng.uniform(0, np.pi)
        p1 = (int(c - np.cos(angle) * rr), int(c - np.sin(angle) * rr))
        p2 = (int(c + np.cos(angle) * rr), int(c + np.sin(angle) * rr))
        cv2.line(mask, p1, p2, 1.0, max(2, int(rr * 0.4)))
        half = mask.shape[0] // 2
        _blend(img, _soften(mask), int(x * scale) - half, int(y * scale) - half,
               rng.uniform(40, 90), 0.9, rng)  # fmt: skip
        placed += 1


def paint_sheet(page: Image, layout: SheetLayout, truth: SheetTruth, dpi: int,
                rng: np.random.Generator) -> Image:  # fmt: skip
    """Return a copy of the clean page with the truth's marks drawn on it."""
    img = page.copy()
    scale = dpi / 72
    for key in sorted(truth.fill_styles):
        b = bubble_for_key(layout, key)
        paint_mark(img, b.cx * scale, b.cy * scale, b.r * scale, truth.fill_styles[key], rng)
    _paint_strays(img, layout, truth.strays, scale, rng)
    return img
