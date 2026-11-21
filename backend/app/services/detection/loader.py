"""Turn uploaded bytes (JPEG, PNG, HEIC from iPhones, or a multi-page PDF) into page images."""

from __future__ import annotations

import io

import cv2
import numpy as np
import numpy.typing as npt
import pillow_heif
from PIL import Image, ImageOps

from app.services.detection.config import DEFAULT_CONFIG, DetectionConfig

pillow_heif.register_heif_opener()

BGR = npt.NDArray[np.uint8]


class UnreadableImageError(ValueError):
    pass


def _downscale(img: BGR, max_long_edge: int) -> BGR:
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long_edge:
        return img
    scale = max_long_edge / long_edge
    return np.asarray(
        cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA),
        np.uint8,
    )


def _pdf_pages(data: bytes, dpi: int) -> list[BGR]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        count = len(doc)
    finally:
        doc.close()
    pages = []
    for i in range(count):
        single = pdfium.PdfDocument(data)
        try:
            bitmap = single[i].render(scale=dpi / 72)
            arr = bitmap.to_numpy()
        finally:
            single.close()
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        pages.append(np.asarray(arr, np.uint8))
    return pages


def _photo(data: bytes) -> BGR:
    """Decode with Pillow (handles HEIC and EXIF rotation), fall back to OpenCV."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            upright = ImageOps.exif_transpose(im) or im
            rgb = np.asarray(upright.convert("RGB"), np.uint8)
        return np.asarray(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), np.uint8)
    except Exception as exc:
        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise UnreadableImageError("not a readable image or PDF") from exc
        return np.asarray(arr, np.uint8)


def load_images(
    data: bytes, filename: str = "", config: DetectionConfig = DEFAULT_CONFIG
) -> list[BGR]:
    """One BGR image per page: a photo gives one, a PDF gives one per page."""
    if not data:
        raise UnreadableImageError("empty file")
    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        try:
            pages = _pdf_pages(data, config.pdf_dpi)
        except Exception as exc:
            raise UnreadableImageError(f"could not read PDF ({exc})") from exc
        if not pages:
            raise UnreadableImageError("PDF has no pages")
        return [_downscale(p, config.max_long_edge) for p in pages]
    return [_downscale(_photo(data), config.max_long_edge)]


__all__ = ["BGR", "UnreadableImageError", "load_images"]
