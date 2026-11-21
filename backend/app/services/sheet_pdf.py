"""Draw a ``SheetLayout`` as a one-page PDF, and render it to an image.

Only draws what the layout says: no coordinates are invented here. Pure black on white
(no grey) so copiers reproduce it faithfully. Output is byte-identical for the same layout.
"""

from __future__ import annotations

import io
from functools import cache

import cv2
import numpy as np
import pypdfium2 as pdfium
import segno
from reportlab.pdfgen.canvas import Canvas

from app.services.layout import Box, SheetLayout

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
LINE = 0.75  # outline thickness, points
ARUCO_DICT = cv2.aruco.DICT_4X4_50
ARUCO_CELLS = 6  # 4x4 data bits + 1-cell black border each side


@cache
def aruco_cells(marker_id: int) -> tuple[tuple[bool, ...], ...]:
    """6x6 grid, True = black, for an ArUco DICT_4X4_50 marker."""
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    img = cv2.aruco.generateImageMarker(dictionary, marker_id, ARUCO_CELLS)
    return tuple(tuple(bool(v < 128) for v in row) for row in img)


def qr_modules(payload: str) -> tuple[tuple[bool, ...], ...]:
    """QR matrix without quiet zone, True = dark. Error correction at least M."""
    code = segno.make(payload, error="m", micro=False)
    return tuple(tuple(bool(v) for v in row) for row in code.matrix)


class _Page:
    """Thin wrapper that takes top-left-origin coordinates like the layout."""

    def __init__(self, canvas: Canvas, page_h: float) -> None:
        self.c = canvas
        self.h = page_h

    def rect(self, box: Box, *, fill: bool = False, stroke: bool = True) -> None:
        self.c.rect(box.x, self.h - box.bottom, box.w, box.h, stroke=int(stroke), fill=int(fill))

    def cells(self, box: Box, grid: tuple[tuple[bool, ...], ...]) -> None:
        """Fill dark cells of a square grid, merging horizontal runs into one rectangle."""
        n = len(grid)
        size = box.w / n
        for r, row in enumerate(grid):
            c = 0
            while c < n:
                if not row[c]:
                    c += 1
                    continue
                start = c
                while c < n and row[c]:
                    c += 1
                y = self.h - (box.y + (r + 1) * size)
                self.c.rect(box.x + start * size, y, (c - start) * size, size, stroke=0, fill=1)

    def text(self, x: float, y_baseline: float, s: str, size: float, *, bold: bool = False,
             align: str = "left") -> None:  # fmt: skip
        self.c.setFont(FONT_BOLD if bold else FONT, size)
        y = self.h - y_baseline
        if align == "right":
            self.c.drawRightString(x, y, s)
        elif align == "center":
            self.c.drawCentredString(x, y, s)
        else:
            self.c.drawString(x, y, s)

    def circle(self, cx: float, cy: float, r: float) -> None:
        self.c.circle(cx, self.h - cy, r, stroke=1, fill=0)


def _fit_text(s: str, size: float, width: float, *, bold: bool = False) -> float:
    """Shrink font size until the text fits the width (never below 6 pt)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    font = FONT_BOLD if bold else FONT
    while size > 6 and stringWidth(s, font, size) > width:
        size -= 0.5
    return size


def render_sheet_pdf(layout: SheetLayout) -> bytes:
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(layout.page_w, layout.page_h), invariant=1)
    canvas.setTitle(f"{layout.title} answer sheet (v{layout.sheet_version})")
    canvas.setAuthor("scioly-grader")
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setLineWidth(LINE)
    page = _Page(canvas, layout.page_h)

    for marker in layout.markers:
        page.cells(marker.box, aruco_cells(marker.id))
    page.cells(layout.qr_box, qr_modules(layout.qr_payload))

    # Header
    hb = layout.header_box
    title_size = _fit_text(layout.title, 16, hb.w, bold=True)
    page.text(hb.x, hb.y + 16, layout.title, title_size, bold=True)
    page.text(
        hb.x,
        hb.y + 31,
        layout.subtitle,
        _fit_text(layout.subtitle, 10, hb.w),
    )
    page.text(hb.x, hb.y + 45, f"Answer sheet  |  Event {layout.event_id}  |  "
              f"Sheet version {layout.sheet_version}", 8.5)  # fmt: skip
    page.text(hb.x, hb.y + 57, "Fill each bubble completely with a dark pencil. "
              "Erase changes fully.", 8)  # fmt: skip
    page.text(hb.x, hb.y + 67, "Print at 100% (actual size). Do not fold or write near "
              "the corner squares.", 7)  # fmt: skip

    # Team name (handwritten, not read)
    nb = layout.name_box
    page.text(nb.x, nb.y - 3, "Team name", 9, bold=True)
    page.rect(nb)

    # Team number grid
    tg = layout.team_grid
    page.text(tg.box.x + tg.box.w / 2, tg.box.y + 8, "Team number", 8, bold=True, align="center")
    for box in tg.write_in:
        page.rect(box)
    for column in tg.columns:
        for b in column:
            page.circle(b.cx, b.cy, b.r)
            page.text(b.cx, b.cy + b.r * 0.45, b.label, b.r * 1.15, align="center")

    # Questions
    for row in layout.questions:
        lb = row.label_box
        page.text(lb.right, lb.y + lb.h / 2 + 3.2, str(row.q), 9, bold=True, align="right")
        for b in row.bubbles:
            page.circle(b.cx, b.cy, b.r)
            page.text(b.cx, b.cy + b.r * 0.42, b.label, b.r * 1.05, align="center")

    canvas.showPage()
    canvas.save()
    return buf.getvalue()


def render_pdf_image(pdf: bytes, dpi: int = 200) -> np.ndarray:
    """First page of a PDF as a greyscale uint8 image (H x W)."""
    doc = pdfium.PdfDocument(pdf)
    try:
        bitmap = doc[0].render(scale=dpi / 72)
        arr = bitmap.to_numpy()
    finally:
        doc.close()
    if arr.ndim == 2:
        return arr.copy()
    code = cv2.COLOR_BGRA2GRAY if arr.shape[2] == 4 else cv2.COLOR_BGR2GRAY
    return cv2.cvtColor(arr, code)


def render_sheet_image(layout: SheetLayout, dpi: int = 200) -> np.ndarray:
    """The sheet exactly as printed, as a greyscale image. Phase 3 fills bubbles on this."""
    return render_pdf_image(render_sheet_pdf(layout), dpi)


def render_sheet_png(layout: SheetLayout, dpi: int = 200) -> bytes:
    ok, encoded = cv2.imencode(".png", render_sheet_image(layout, dpi))
    if not ok:  # pragma: no cover - OpenCV only fails on invalid arrays
        raise RuntimeError("could not encode sheet image as PNG")
    return encoded.tobytes()
