"""Find the sheet in a photo, straighten it, and read its QR code."""

from __future__ import annotations

import json
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from app.services.detection.config import DetectionConfig
from app.services.layout import PAGE_H, PAGE_W, page_markers, page_qr_box
from app.services.sheet_pdf import ARUCO_DICT

Gray = npt.NDArray[np.uint8]
MARKER_IDS = (0, 1, 2, 3)


def _detector(polygon_accuracy: float) -> cv2.aruco.ArucoDetector:
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 63
    params.adaptiveThreshWinSizeStep = 6
    params.minMarkerPerimeterRate = 0.01
    params.polygonalApproxAccuracyRate = polygon_accuracy
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT), params)


_DETECTORS = (_detector(0.03), _detector(0.06))
_CLAHE = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))


def find_markers(gray: Gray) -> dict[int, npt.NDArray[np.float32]]:
    """Corner markers 0-3 as 4x2 arrays (marker's own TL, TR, BR, BL), in image pixels.
    Tries a few preprocessings so small, blurry or badly lit markers are still found."""
    found: dict[int, npt.NDArray[np.float32]] = {}
    attempts: list[tuple[Gray, float]] = [(gray, 1.0)]
    attempts.append((np.asarray(_CLAHE.apply(gray), np.uint8), 1.0))
    if max(gray.shape) < 2600:
        big = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        attempts.append((np.asarray(big, np.uint8), 2.0))
    attempts.append((np.asarray(cv2.GaussianBlur(gray, (0, 0), 1.2), np.uint8), 1.0))
    for img, scale in attempts:
        for detector in _DETECTORS:
            corners, ids, _ = detector.detectMarkers(img)
            if ids is None:
                continue
            for marker_id, quad in zip(ids.flatten(), corners, strict=True):
                if int(marker_id) in MARKER_IDS and int(marker_id) not in found:
                    found[int(marker_id)] = (quad.reshape(4, 2) / scale).astype(np.float32)
            if len(found) == 4:
                return found
    return found


@dataclass(frozen=True)
class Warp:
    page: Gray  # straightened page at config.dpi, layout coordinates * scale
    homography: npt.NDArray[np.float64]  # photo pixels -> page pixels
    markers: tuple[int, ...]
    error_px: float  # mean marker-corner reprojection error on the page


def warp_page(gray: Gray, markers: dict[int, npt.NDArray[np.float32]], dpi: int) -> Warp:
    """Homography from every found marker corner to its printed position. Marker positions
    are the same on every event's sheet, so this needs no event information."""
    s = dpi / 72
    src, dst = [], []
    for m in page_markers():
        if m.id not in markers:
            continue
        b = m.box
        dst += [
            (b.x * s, b.y * s),
            (b.right * s, b.y * s),
            (b.right * s, b.bottom * s),
            (b.x * s, b.bottom * s),
        ]
        src += markers[m.id].tolist()
    src_a, dst_a = np.array(src, np.float32), np.array(dst, np.float32)
    homography, _ = cv2.findHomography(src_a, dst_a, cv2.RANSAC, 6.0)
    if homography is None:
        homography, _ = cv2.findHomography(src_a, dst_a, 0)
    size = (round(PAGE_W * s), round(PAGE_H * s))
    page = cv2.warpPerspective(
        gray, homography, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    projected = cv2.perspectiveTransform(src_a[None], homography)[0]
    error = float(np.linalg.norm(projected - dst_a, axis=1).mean())
    return Warp(
        np.asarray(page, np.uint8),
        np.asarray(homography, np.float64),
        tuple(sorted(markers)),
        error,
    )


def _decode(img: Gray) -> str | None:
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return text or None


def parse_qr(text: str | None) -> tuple[str, int] | None:
    if not text:
        return None
    try:
        data = json.loads(text)
        return str(data["e"]), int(data["v"])
    except (ValueError, KeyError, TypeError):
        return None


def read_qr(page: Gray, photo: Gray, dpi: int) -> tuple[str, int] | None:
    """QR from the straightened page's QR area first, then the whole page, then the photo.
    The QR position does not depend on the event, so any layout gives the box."""
    s = dpi / 72
    box = page_qr_box().grow(10)
    x0, y0 = max(0, int(box.x * s)), max(0, int(box.y * s))
    crop = page[y0 : int(box.bottom * s), x0 : int(box.right * s)]
    candidates = [
        crop,
        cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
        _CLAHE.apply(crop),
        page,
        photo,
    ]
    for img in candidates:
        parsed = parse_qr(_decode(np.asarray(img, np.uint8)))
        if parsed:
            return parsed
    return None


def normalise_lighting(page: Gray, config: DetectionConfig) -> npt.NDArray[np.float32]:
    """Darkness 0 (paper) .. 1 (black), with shadows, glare and gradients divided out.
    The paper's brightness is estimated by closing (removing dark marks smaller than the
    window) and smoothing; each pixel is then compared with its local paper level."""
    k = max(15, int(page.shape[1] * config.background_kernel_frac) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    paper = cv2.morphologyEx(page, cv2.MORPH_CLOSE, kernel)
    paper = cv2.GaussianBlur(paper, (0, 0), k / 2).astype(np.float32)
    ratio = page.astype(np.float32) / np.maximum(paper, 1.0)
    return np.asarray(np.clip(1.0 - ratio, 0.0, 1.0), np.float32)
