from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz

from .models import PlacedStamp
from .pdf_geometry import displayed_rect_to_pdf_rect


def signature_image_bytes_for_pdf(image_path: str, rotation: int = 0) -> bytes:
    """Return PNG bytes matching the Qt preview path.

    The GUI preview draws signature images with Qt. Saving used to pass the
    original PNG path directly to MuPDF, which means Qt and MuPDF could disagree
    about image orientation metadata or pixel normalization. Normalize through
    Qt first, then embed those exact PNG bytes with MuPDF.
    """
    try:
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
        from PyQt6.QtGui import QImageReader, QTransform
    except ImportError:
        # Headless test/container environments may lack desktop libraries needed
        # by QtGui. The desktop app itself requires Qt; this fallback keeps the
        # non-GUI PDF tests runnable there.
        if rotation % 360:
            raise
        return Path(image_path).read_bytes()

    reader = QImageReader(image_path)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(f"Could not read signature image: {image_path}")

    normalized_rotation = rotation % 360
    if normalized_rotation:
        image = image.transformed(QTransform().rotate(normalized_rotation))

    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("Could not prepare signature image for PDF output")
    if not image.save(buffer, "PNG"):
        raise ValueError("Could not encode signature image for PDF output")
    buffer.close()
    return bytes(data)


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
                if stamp.kind == "signature":
                    image_bytes = signature_image_bytes_for_pdf(stamp.image_path, stamp.rotation)
                    write_rotation = page.rotation % 360
                    page.insert_image(rect, stream=image_bytes, keep_proportion=True, overlay=True, rotate=write_rotation)
                else:
                    write_rotation = (page.rotation + stamp.rotation) % 360
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
