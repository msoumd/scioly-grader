"""Turn a flat painted page into a fake phone photo under one named condition.

Each condition has a strength in [0, 1] (mild to harsh) and draws every random choice
from the generator it is given, so the same seed always makes the same JPEG.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

Image = npt.NDArray[np.uint8]
FloatImage = npt.NDArray[np.float32]

CONDITIONS: tuple[str, ...] = (
    "clean",  # flat, square-on, well lit: like a scanner
    "rotate_small",  # +/- 2-5 degrees
    "rotate_large",  # +/- 8-15 degrees
    "rotate_90",
    "rotate_180",
    "perspective",  # phone tilted, up to ~25 degrees
    "far",  # phone held far away: page small in frame
    "near",  # page fills the frame
    "blur_focus",
    "blur_motion",
    "shadow",  # hand / phone shadow band across the page
    "uneven_light",
    "low_light",  # dark and noisy
    "jpeg_heavy",  # strong compression
    "color_cast",  # warm indoor light
    "curl",  # paper not lying flat
    "corner_edge",  # one page corner almost cut off by the frame
    "clutter",  # busy desk around the page
    "phone",  # realistic mix of mild problems
)

DEFAULT_SIZE = (1500, 2000)  # width, height: a downscaled portrait phone photo


@dataclass(frozen=True)
class Photo:
    jpeg: bytes
    corners: list[tuple[float, float]]  # page TL, TR, BR, BL in image pixels
    params: dict[str, Any]

    def decode(self) -> Image:
        return np.asarray(cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_COLOR),
                          np.uint8)  # fmt: skip


def _sign(rng: np.random.Generator) -> float:
    return 1.0 if rng.random() < 0.5 else -1.0


def _mild(rng: np.random.Generator) -> dict[str, Any]:
    """Small everyday imperfections every photo has."""
    return {
        "angle": float(rng.normal(0, 1.0)),
        "fill": float(rng.uniform(0.78, 0.9)),
        "tilt": float(rng.uniform(0, 0.03)),
        "tilt_side": int(rng.integers(4)),
        "shift": [float(rng.uniform(-0.03, 0.03)), float(rng.uniform(-0.03, 0.03))],
        "curl": 0.0,
        "background": "plain",
        "gradient": float(rng.uniform(0, 0.12)),
        "light_dir": float(rng.uniform(0, 2 * np.pi)),
        "shadow": 0.0,
        "dark": 1.0,
        "noise": float(rng.uniform(1.5, 3.5)),
        "cast": [float(rng.uniform(0.96, 1.0)), 1.0, float(rng.uniform(1.0, 1.03))],
        "blur": float(rng.uniform(0.3, 0.8)),
        "motion": 0,
        "jpeg": int(rng.integers(85, 96)),
        "corner": None,
    }


def photo_params(condition: str, rng: np.random.Generator, strength: float) -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; choose from {', '.join(CONDITIONS)}")
    s = float(np.clip(strength, 0, 1))
    p = _mild(rng)
    p["condition"], p["strength"] = condition, round(s, 3)

    if condition == "clean":
        p.update(angle=0.0, tilt=0.0, shift=[0.0, 0.0], gradient=0.0, noise=0.0,
                 cast=[1.0, 1.0, 1.0], blur=0.0, jpeg=95, fill=0.9)  # fmt: skip
    elif condition == "rotate_small":
        p["angle"] = _sign(rng) * (2 + 3 * s)
    elif condition == "rotate_large":
        p["angle"] = _sign(rng) * (8 + 7 * s)
    elif condition == "rotate_90":
        p["angle"] = _sign(rng) * 90 + float(rng.normal(0, 1.0))
    elif condition == "rotate_180":
        p["angle"] = 180 + float(rng.normal(0, 1.0))
    elif condition == "perspective":
        p["tilt"] = 0.08 + 0.22 * s
    elif condition == "far":
        p["fill"] = 0.55 - 0.2 * s
    elif condition == "near":
        p["fill"] = 0.93 + 0.05 * s
    elif condition == "blur_focus":
        p["blur"] = 1.2 + 1.8 * s
    elif condition == "blur_motion":
        p["motion"], p["motion_angle"] = int(7 + 14 * s), float(rng.uniform(0, 180))
    elif condition == "shadow":
        p["shadow"] = 0.3 + 0.35 * s
    elif condition == "uneven_light":
        p["gradient"] = 0.25 + 0.35 * s
    elif condition == "low_light":
        p["dark"], p["noise"] = 0.6 - 0.25 * s, 6 + 10 * s
    elif condition == "jpeg_heavy":
        p["jpeg"] = int(45 - 25 * s)
    elif condition == "color_cast":
        p["cast"] = [0.85 - 0.15 * s, 0.95 - 0.05 * s, 1.0 + 0.08 * s]
    elif condition == "curl":
        p["curl"] = 0.01 + 0.02 * s
    elif condition == "corner_edge":
        p["corner"], p["fill"] = int(rng.integers(4)), 0.82
        p["corner_margin"] = 0.02 - 0.015 * s
    elif condition == "clutter":
        p["background"] = "clutter"
    elif condition == "phone":
        if rng.random() < 0.5:
            p["angle"] = _sign(rng) * float(rng.uniform(1, 5))
        if rng.random() < 0.5:
            p["tilt"] = float(rng.uniform(0.04, 0.14))
        if rng.random() < 0.3:
            p["shadow"] = float(rng.uniform(0.2, 0.4))
        if rng.random() < 0.5:
            p["gradient"] = float(rng.uniform(0.15, 0.35))
        if rng.random() < 0.3:
            p["blur"] = float(rng.uniform(0.8, 1.5))
        if rng.random() < 0.5:
            p["cast"] = [float(rng.uniform(0.82, 0.95)), 0.97, float(rng.uniform(1.0, 1.06))]
        if rng.random() < 0.3:
            p["curl"] = float(rng.uniform(0.005, 0.015))
        if rng.random() < 0.5:
            p["background"] = "clutter"
        p["jpeg"], p["noise"] = int(rng.integers(70, 91)), float(rng.uniform(3, 6))
    return p


# --- image operations ---------------------------------------------------------


def _curl(page: FloatImage, amount: float) -> FloatImage:
    h, w = page.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dy = amount * h * np.sin(np.pi * xx / w)
    dx = 0.5 * amount * w * np.sin(np.pi * yy / h)
    out = cv2.remap(page, xx - dx, yy - dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return np.asarray(out, np.float32)


def _corners(page_w: int, page_h: int, p: dict[str, Any], size: tuple[int, int]) -> np.ndarray:
    W, H = size
    c = np.array([[-page_w, -page_h], [page_w, -page_h], [page_w, page_h], [-page_w, page_h]],
                 np.float64) / 2  # fmt: skip
    t = p["tilt"]
    side = p["tilt_side"]  # which edge is farther from the camera: 0 top, 1 right, 2 bottom, 3 left
    far = {0: [0, 1], 1: [1, 2], 2: [2, 3], 3: [3, 0]}[side]
    centroid = c.mean(axis=0)
    axis = 0 if side in (0, 2) else 1  # shrink along the edge's own direction
    for i in far:
        c[i, axis] = centroid[axis] + (c[i, axis] - centroid[axis]) * (1 - t)
        c[i, 1 - axis] *= 1 - t / 2
    a = np.deg2rad(p["angle"])
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    c = c @ rot.T
    span = c.max(axis=0) - c.min(axis=0)
    c *= p["fill"] * min(W / span[0], H / span[1])
    c += np.array([W / 2 + p["shift"][0] * W, H / 2 + p["shift"][1] * H])
    if p.get("corner") is not None:
        k, m = p["corner"], p["corner_margin"]
        tx = m * W - c[k, 0] if c[k, 0] < W / 2 else W - m * W - c[k, 0]
        ty = m * H - c[k, 1] if c[k, 1] < H / 2 else H - m * H - c[k, 1]
        c += np.array([tx, ty])
        for _ in range(40):  # shrink toward that corner until the whole page is in frame
            if (c >= 0).all() and (c[:, 0] <= W).all() and (c[:, 1] <= H).all():
                break
            c = c[k] + (c - c[k]) * 0.97
    return c


def _background(size: tuple[int, int], kind: str, rng: np.random.Generator) -> FloatImage:
    W, H = size
    base = np.array([rng.uniform(150, 200), rng.uniform(160, 205), rng.uniform(170, 215)])
    bg = np.ones((H, W, 3), np.float32) * base.astype(np.float32)
    grain = np.asarray(cv2.GaussianBlur(rng.normal(0, 8, (H, W)).astype(np.float32), (0, 0), 3))
    bg += grain[..., None]
    if kind == "clutter":
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        a = rng.uniform(0, np.pi)
        stripes = np.sin((xx * np.cos(a) + yy * np.sin(a)) / rng.uniform(6, 14))
        stripes += 0.5 * np.sin((xx * np.cos(a) + yy * np.sin(a)) / rng.uniform(25, 60))
        bg = bg * 0.75 + (stripes[..., None] * 18).astype(np.float32)
        for _ in range(int(rng.integers(4, 9))):
            color = tuple(float(v) for v in rng.uniform(20, 240, 3))
            x, y = int(rng.uniform(0, W)), int(rng.uniform(0, H))
            if rng.random() < 0.5:
                w2, h2 = int(rng.uniform(40, 300)), int(rng.uniform(20, 200))
                cv2.rectangle(bg, (x, y), (x + w2, y + h2), color, -1)
            else:
                axes = (int(rng.uniform(20, 150)), int(rng.uniform(10, 60)))
                cv2.ellipse(bg, (x, y), axes, float(rng.uniform(0, 180)), 0, 360, color, -1)
    return np.clip(bg, 0, 255).astype(np.float32)


def _lighting(size: tuple[int, int], p: dict[str, Any], rng: np.random.Generator) -> FloatImage:
    W, H = size
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = p["light_dir"]
    proj = (xx - W / 2) * np.cos(d) + (yy - H / 2) * np.sin(d)
    proj = (proj - proj.min()) / max(float(np.ptp(proj)), 1.0)
    light = 1 - p["gradient"] * proj
    if p["shadow"] > 0:
        a = rng.uniform(0, np.pi)
        nx, ny = np.cos(a), np.sin(a)
        offset = rng.uniform(-0.25, 0.25) * min(W, H)
        dist = (xx - W / 2) * nx + (yy - H / 2) * ny - offset
        width = rng.uniform(0.15, 0.35) * min(W, H)
        band = (np.abs(dist) < width / 2).astype(np.float32)
        band = np.asarray(cv2.GaussianBlur(band, (0, 0), min(W, H) * 0.03), np.float32)
        light *= 1 - p["shadow"] * band
    return np.asarray(light * p["dark"], np.float32)


def _motion_kernel(length: int, angle: float) -> FloatImage:
    k = np.zeros((length, length), np.float32)
    c = length // 2
    dx, dy = np.cos(np.deg2rad(angle)) * c, np.sin(np.deg2rad(angle)) * c
    cv2.line(k, (int(c - dx), int(c - dy)), (int(c + dx), int(c + dy)), 1.0, 1)
    return k / max(float(k.sum()), 1.0)


def photograph(
    page: Image,
    condition: str,
    rng: np.random.Generator,
    size: tuple[int, int] = DEFAULT_SIZE,
    strength: float | None = None,
) -> Photo:
    """Fake a phone photo of a (greyscale) page under ``condition``."""
    s = float(rng.uniform(0.5, 1.0)) if strength is None else strength
    p = photo_params(condition, rng, s)
    W, H = size

    src = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR).astype(np.float32)
    if p["curl"]:
        src = _curl(src, p["curl"])
    ph, pw = page.shape[:2]
    dst = _corners(pw, ph, p, size)
    src_quad = np.array([[0, 0], [pw, 0], [pw, ph], [0, ph]], np.float32)
    homography = cv2.getPerspectiveTransform(src_quad, dst.astype(np.float32))

    bg = _background(size, p["background"], rng)
    warped = cv2.warpPerspective(src, homography, (W, H), flags=cv2.INTER_AREA)
    inside = cv2.warpPerspective(np.ones((ph, pw), np.float32), homography, (W, H))[..., None]
    img = bg * (1 - inside) + warped * inside

    img *= _lighting(size, p, rng)[..., None]
    img *= np.array(p["cast"], np.float32)
    if p["blur"] > 0:
        img = cv2.GaussianBlur(img, (0, 0), p["blur"])
    if p["motion"]:
        img = cv2.filter2D(img, -1, _motion_kernel(p["motion"], p["motion_angle"]))
    if p["noise"] > 0:
        img += rng.normal(0, p["noise"], img.shape).astype(np.float32)
    out = np.clip(img, 0, 255).astype(np.uint8)

    ok, encoded = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(p["jpeg"])])
    if not ok:  # pragma: no cover
        raise RuntimeError("JPEG encoding failed")
    corners = [(round(float(x), 2), round(float(y), 2)) for x, y in dst]
    return Photo(jpeg=encoded.tobytes(), corners=corners, params=p)
