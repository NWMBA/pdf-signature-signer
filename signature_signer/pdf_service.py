from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtGui import QImage, QPixmap

from .models import PlacedSignature


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

    def save_with_signatures(self, output_path: str, signatures: list[PlacedSignature]) -> None:
        if not self.path:
            raise ValueError("No PDF open")

        source = fitz.open(self.path)
        try:
            for sig in signatures:
                page = source[sig.page_index]
                rect = fitz.Rect(sig.x, sig.y, sig.x + sig.width, sig.y + sig.height)
                page.insert_image(rect, filename=sig.image_path, keep_proportion=True, overlay=True)
            source.save(output_path)
        finally:
            source.close()

    def _page(self, page_index: int) -> fitz.Page:
        if self.doc is None:
            raise ValueError("No PDF open")
        return self.doc[page_index]
