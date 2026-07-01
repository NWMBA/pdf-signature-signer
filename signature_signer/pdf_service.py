from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz

from .models import PlacedStamp
from .pdf_geometry import displayed_rect_to_pdf_rect


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

    def render_page(self, page_index: int, zoom: float):
        from PyQt6.QtGui import QImage, QPixmap

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

        source_path = Path(self.path).resolve()
        target_path = Path(output_path).resolve()
        overwriting_original = source_path == target_path
        temp_output: Path | None = None
        source = fitz.open(source_path)
        try:
            for stamp in stamps:
                page = source[stamp.page_index]
                displayed_rect = fitz.Rect(stamp.x, stamp.y, stamp.x + stamp.width, stamp.y + stamp.height)
                rect = displayed_rect_to_pdf_rect(page, displayed_rect)
                write_rotation = (page.rotation + stamp.rotation) % 360
                if stamp.kind == "signature":
                    page.insert_image(rect, filename=stamp.image_path, keep_proportion=True, overlay=True, rotate=write_rotation)
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
                        rotate=write_rotation,
                    )

            if overwriting_original:
                with NamedTemporaryFile(
                    prefix=f".{source_path.stem}-",
                    suffix=source_path.suffix,
                    dir=source_path.parent,
                    delete=False,
                ) as temp_file:
                    temp_output = Path(temp_file.name)
                source.save(temp_output, garbage=4, deflate=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                source.save(target_path, garbage=4, deflate=True)
        finally:
            source.close()

        if overwriting_original and temp_output is not None:
            if self.doc is not None:
                self.doc.close()
                self.doc = None
            temp_output.replace(source_path)
            self.doc = fitz.open(source_path)
            self.path = str(source_path)

    def _page(self, page_index: int) -> fitz.Page:
        if self.doc is None:
            raise ValueError("No PDF open")
        return self.doc[page_index]
