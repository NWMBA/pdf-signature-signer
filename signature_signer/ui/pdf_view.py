from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..models import PlacedSignature


@dataclass
class PageMetrics:
    page_index: int
    pdf_width: float
    pdf_height: float
    scale: float


class PDFPageWidget(QLabel):
    placementRequested = pyqtSignal(int, float, float)
    signatureMoved = pyqtSignal(int, int, float, float)
    signatureSelected = pyqtSignal(int)
    deleteRequested = pyqtSignal(int)
    scaleAdjustRequested = pyqtSignal(int)
    previewPositionChanged = pyqtSignal(int, float, float)

    def __init__(self, page_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self.metrics = PageMetrics(page_index, 1.0, 1.0, 1.0)
        self.signatures: list[PlacedSignature] = []
        self.preview_rect: QRectF | None = None
        self.selected_signature_id: int | None = None
        self.placing_enabled = False
        self.drag_signature_id: int | None = None
        self.drag_offset = QPointF()
        self.preview_size_pdf = QSizeF(140.0, 49.0)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        delete_action = QAction(self)
        delete_action.setShortcut("Delete")
        delete_action.triggered.connect(self._delete_selected)
        self.addAction(delete_action)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

    def set_page(self, pixmap: QPixmap, pdf_width: float, pdf_height: float, scale: float) -> None:
        self.setPixmap(pixmap)
        self.resize(pixmap.size())
        self.metrics = PageMetrics(self.page_index, pdf_width, pdf_height, scale)
        self.update()

    def set_signatures(self, signatures: list[PlacedSignature], selected_signature_id: int | None) -> None:
        self.signatures = signatures
        self.selected_signature_id = selected_signature_id
        self.update()

    def set_preview(self, rect: QRectF | None) -> None:
        self.preview_rect = rect
        self.update()

    def set_placing_enabled(self, enabled: bool) -> None:
        self.placing_enabled = enabled
        if not enabled:
            self.preview_rect = None
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self.drag_signature_id is not None:
            x = max(0.0, min(pos.x() - self.drag_offset.x(), self.width()))
            y = max(0.0, min(pos.y() - self.drag_offset.y(), self.height()))
            pdf_x, pdf_y = self._widget_to_pdf(QPointF(x, y))
            self.signatureMoved.emit(self.page_index, self.drag_signature_id, pdf_x, pdf_y)
            return

        if self.placing_enabled:
            pdf_x, pdf_y = self._widget_to_pdf(pos)
            self.previewPositionChanged.emit(self.page_index, pdf_x, pdf_y)
            self.preview_rect = self._preview_rect_for_widget_pos(pos)
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        hit = self._hit_test(pos)
        if hit is not None:
            self.selected_signature_id = hit.id
            self.signatureSelected.emit(hit.id)
            rect = self._pdf_rect_to_widget(hit)
            self.drag_signature_id = hit.id
            self.drag_offset = QPointF(pos.x() - rect.x(), pos.y() - rect.y())
            self.update()
            return

        if self.placing_enabled:
            pdf_x, pdf_y = self._widget_to_pdf(pos)
            self.placementRequested.emit(self.page_index, pdf_x, pdf_y)
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.drag_signature_id = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.placing_enabled:
            step = 1 if event.angleDelta().y() > 0 else -1
            self.scaleAdjustRequested.emit(step)
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for sig in self.signatures:
            rect = self._pdf_rect_to_widget(sig)
            pen = QPen(QColor("#cc3333") if sig.id == self.selected_signature_id else QColor("#2277cc"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(rect)
            if Path(sig.image_path).is_file():
                pix = QPixmap(sig.image_path)
                if not pix.isNull():
                    painter.drawPixmap(rect.toRect(), pix)

        if self.preview_rect is not None:
            pen = QPen(QColor("#22aa55"))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(self.preview_rect)
            painter.fillRect(self.preview_rect, QColor(34, 170, 85, 40))

    def set_preview_size_pdf(self, width: float, height: float) -> None:
        self.preview_size_pdf = QSizeF(width, height)
        self.update_preview_from_current_rect()

    def update_preview_from_current_rect(self) -> None:
        if self.preview_rect is None:
            return
        center = self.preview_rect.center()
        self.preview_rect = self._preview_rect_for_widget_pos(center)
        self.update()

    def _preview_rect_for_widget_pos(self, pos: QPointF) -> QRectF:
        scale = self.metrics.scale or 1.0
        width = self.preview_size_pdf.width() * scale
        height = self.preview_size_pdf.height() * scale
        x = max(0.0, min(pos.x() - width / 2, self.width() - width))
        y = max(0.0, min(pos.y() - height / 2, self.height() - height))
        return QRectF(x, y, width, height)

    def _widget_to_pdf(self, pos: QPointF) -> tuple[float, float]:
        scale = self.metrics.scale or 1.0
        return pos.x() / scale, pos.y() / scale

    def _pdf_rect_to_widget(self, sig: PlacedSignature) -> QRectF:
        scale = self.metrics.scale or 1.0
        return QRectF(sig.x * scale, sig.y * scale, sig.width * scale, sig.height * scale)

    def _hit_test(self, pos: QPointF) -> PlacedSignature | None:
        for sig in reversed(self.signatures):
            if self._pdf_rect_to_widget(sig).contains(pos):
                return sig
        return None

    def _delete_selected(self) -> None:
        if self.selected_signature_id is not None:
            self.deleteRequested.emit(self.selected_signature_id)


class PDFView(QScrollArea):
    placementRequested = pyqtSignal(int, float, float)
    signatureMoved = pyqtSignal(int, int, float, float)
    signatureSelected = pyqtSignal(int)
    deleteRequested = pyqtSignal(int)
    scaleAdjustRequested = pyqtSignal(int)
    previewPositionChanged = pyqtSignal(int, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(24)
        self.page_widgets: list[PDFPageWidget] = []
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    def clear_pages(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.page_widgets.clear()

    def set_pages(self, pages: list[tuple[QPixmap, float, float, float]]) -> None:
        self.clear_pages()
        for page_index, (pixmap, pdf_width, pdf_height, scale) in enumerate(pages):
            widget = PDFPageWidget(page_index)
            widget.set_page(pixmap, pdf_width, pdf_height, scale)
            widget.placementRequested.connect(self.placementRequested)
            widget.signatureMoved.connect(self.signatureMoved)
            widget.signatureSelected.connect(self.signatureSelected)
            widget.deleteRequested.connect(self.deleteRequested)
            widget.scaleAdjustRequested.connect(self.scaleAdjustRequested)
            widget.previewPositionChanged.connect(self.previewPositionChanged)
            self.layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.page_widgets.append(widget)
        self.layout.addStretch(1)

    def update_page_signatures(self, page_index: int, signatures: list[PlacedSignature], selected_signature_id: int | None, placing_enabled: bool) -> None:
        if 0 <= page_index < len(self.page_widgets):
            widget = self.page_widgets[page_index]
            widget.set_signatures(signatures, selected_signature_id)
            widget.set_placing_enabled(placing_enabled)

    def set_placing_enabled(self, enabled: bool) -> None:
        for widget in self.page_widgets:
            widget.set_placing_enabled(enabled)

    def set_preview_size_pdf(self, width: float, height: float) -> None:
        for widget in self.page_widgets:
            widget.set_preview_size_pdf(width, height)
