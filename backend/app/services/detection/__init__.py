"""Read a photographed or scanned bubble sheet: find the page, identify the event from
the QR code, read the team number and every bubble, score it, and flag anything uncertain.

Classic computer vision (OpenCV), no machine learning. Entry points:

- ``load_images(data, filename)``: bytes of a JPEG/PNG/HEIC/PDF -> list of page images
- ``read_sheet(image, lookup)``: one page image -> ``SheetScan``
"""

from app.services.detection.loader import load_images
from app.services.detection.reader import SheetScan, read_sheet

__all__ = ["SheetScan", "load_images", "read_sheet"]
