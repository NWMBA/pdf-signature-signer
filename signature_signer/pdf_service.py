from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtGui import QImage, QPixmap

from .models import PlacedStamp


class PDFDocumentService:
    def __init__(self) -> None:
        self.doc: fitz.Document | None = None
        self.path: str | None = None

    def open(self, path: str) -> None:
        self.close()
        self.doc = fitz.open(path)
        self.path = path
        if self.doc.needs_pass:
            raise ValueError("Password-protected PDFs are not supported in this MVP.")

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.path = None

    def page_count(self) -> int:
        return 0 if self.doc is None else len(self.doc)

    def page_size(self, page_index: int) -> tuple[float, float]:
        page = self._page(page_index)
        rect = page.rect
        return rect.width, rect.height

    def render_page(self, page_index: int, zoom: float) -> QPixmap:
        page = self._page(page_index)
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(image)

    def save_with_stamps(self, output_path: str, stamps: list[PlacedStamp]) -> None:
        if not self.path:
            raise ValueError("No PDF open")

        source = fitz.open(self.path)
        try:
            for stamp in stamps:
                page = source[stamp.page_index]
                rect = fitz.Rect(stamp.x, stamp.y, stamp.x + stamp.width, stamp.y + stamp.height)
                if stamp.kind == "signature":
                    page.insert_image(rect, filename=stamp.image_path, keep_proportion=True, overlay=True)
                else:
                    fontsize = max(8.0, stamp.height * 0.58)
                    page.insert_textbox(
                        rect,
                        stamp.text,
                        fontname="helv",
                        fontsize=fontsize,
                        color=(0, 0, 0),
                        align=fitz.TEXT_ALIGN_LEFT,
                        overlay=True,
                    )
            source.save(output_path)
        finally:
            source.close()

    def _page(self, page_index: int) -> fitz.Page:
        if self.doc is None:
            raise ValueError("No PDF open")
        return self.doc[page_index]
