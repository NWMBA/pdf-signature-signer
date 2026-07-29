from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz

from .models import PlacedStamp

OVERLAY_SCALE = 3.0


def signature_image_bytes_for_pdf(image_path: str, rotation: int = 0) -> bytes:
    """Return PNG bytes for both preview and PDF output.

    The signer has one non-negotiable rule: what the user sees in the live
    preview must be what gets saved into the PDF. Qt's image reader is used here
    as the single source of truth for image decoding, including orientation
    metadata from files created by phones or scanners. Manual stamp rotation is
    still baked in explicitly so the Rotate button remains predictable.
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


def _qimage_to_png_bytes(image) -> bytes:
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("Could not prepare transparent stamp overlay")
    if not image.save(buffer, "PNG"):
        raise ValueError("Could not encode transparent stamp overlay")
    buffer.close()
    return bytes(data)


def _pixmap_to_qimage(pix: fitz.Pixmap):
    from PyQt6.QtGui import QImage

    return QImage(
        pix.samples,
        pix.width,
        pix.height,
        pix.stride,
        QImage.Format.Format_RGB888,
    ).copy()


def _draw_signature_stamp(painter, stamp: PlacedStamp, scale: float) -> None:
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage

    signature = QImage()
    image_bytes = signature_image_bytes_for_pdf(stamp.image_path, stamp.rotation)
    if not signature.loadFromData(image_bytes, "PNG") or signature.isNull():
        raise ValueError(f"Could not load signature image for drawing: {stamp.image_path}")

    target = QRectF(stamp.x * scale, stamp.y * scale, stamp.width * scale, stamp.height * scale)
    painter.drawImage(target, signature)


def _draw_text_stamp(painter, stamp: PlacedStamp, scale: float) -> None:
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont

    painter.save()
    painter.setPen(QColor("#000000"))
    font = QFont("Helvetica")
    font.setPixelSize(max(10, int(stamp.height * scale * 0.58)))
    painter.setFont(font)
    rect = QRectF(stamp.x * scale, stamp.y * scale, stamp.width * scale, stamp.height * scale)
    painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, stamp.text)
    painter.restore()


def _stamp_for_overlay_coordinates(page: fitz.Page, stamp: PlacedStamp) -> PlacedStamp:
    displayed_rect = fitz.Rect(stamp.x, stamp.y, stamp.x + stamp.width, stamp.y + stamp.height)
    overlay_rect = fitz.Rect(displayed_rect) * page.derotation_matrix
    overlay_rect.normalize()
    return replace(
        stamp,
        x=overlay_rect.x0,
        y=overlay_rect.y0,
        width=overlay_rect.width,
        height=overlay_rect.height,
        rotation=(stamp.rotation + page.rotation) % 360,
    )


def _transparent_overlay_png_bytes(
    page: fitz.Page,
    stamps: list[PlacedStamp],
    scale: float = OVERLAY_SCALE,
) -> bytes:
    """Draw stamps into a full-page transparent overlay image.

    The output PDF keeps the original page content underneath, so text remains
    selectable. Stamps are drawn into one page-sized image first, then that image
    is inserted over the full page. This avoids the old small-image placement
    path that was vulnerable to page/image transform surprises.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter

    pixel_width = max(1, int(round(page.rect.width * scale)))
    pixel_height = max(1, int(round(page.rect.height * scale)))
    image = QImage(pixel_width, pixel_height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    try:
        for stamp in stamps:
            overlay_stamp = _stamp_for_overlay_coordinates(page, stamp)
            if overlay_stamp.kind == "signature":
                _draw_signature_stamp(painter, overlay_stamp, scale)
            else:
                _draw_text_stamp(painter, overlay_stamp, scale)
    finally:
        painter.end()
    return _qimage_to_png_bytes(image)


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
        from PyQt6.QtGui import QPixmap

        page = self._page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return QPixmap.fromImage(_pixmap_to_qimage(pix))

    def save_with_stamps(self, output_path: str, stamps: list[PlacedStamp]) -> None:
        if not self.path:
            raise ValueError("No PDF open")

        source_path = Path(self.path).resolve()
        target_path = Path(output_path).resolve()
        overwriting_original = source_path == target_path
        temp_output: Path | None = None
        source = fitz.open(source_path)
        output = fitz.open()
        stamps_by_page: dict[int, list[PlacedStamp]] = defaultdict(list)
        for stamp in stamps:
            stamps_by_page[stamp.page_index].append(stamp)

        try:
            output.insert_pdf(source)
            for page_index, page_stamps in stamps_by_page.items():
                if not page_stamps:
                    continue
                page = output[page_index]
                overlay_png = _transparent_overlay_png_bytes(page, page_stamps)
                page.insert_image(page.rect, stream=overlay_png, keep_proportion=False, overlay=True)

            if overwriting_original:
                with NamedTemporaryFile(
                    prefix=f".{source_path.stem}-",
                    suffix=source_path.suffix,
                    dir=source_path.parent,
                    delete=False,
                ) as temp_file:
                    temp_output = Path(temp_file.name)
                output.save(temp_output, garbage=4, deflate=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                output.save(target_path, garbage=4, deflate=True)
        finally:
            output.close()
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
