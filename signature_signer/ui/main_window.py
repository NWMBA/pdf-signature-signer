from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QToolBar,
)

from ..config import ConfigManager
from ..models import AppConfig, DocumentState, PlacedSignature
from ..pdf_service import PDFDocumentService
from .pdf_view import PDFView


class MainWindow(QMainWindow):
    def __init__(self, config_manager: ConfigManager, initial_pdf_path: str | None = None) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.config: AppConfig = self.config_manager.load()
        self.pdf_service = PDFDocumentService()
        self.state = DocumentState(zoom=1.0)
        self.signature_scale = max(0.2, self.config.default_scale)
        self.next_signature_id = 1
        self.placing_enabled = True
        self.preview_page_index: int | None = None
        self.preview_pdf_x: float | None = None
        self.preview_pdf_y: float | None = None
        self.setWindowTitle("Signature Signer")
        self.resize(self.config.window_width, self.config.window_height)

        self.pdf_view = PDFView()
        self.pdf_view.placementRequested.connect(self.place_signature)
        self.pdf_view.signatureMoved.connect(self.move_signature)
        self.pdf_view.signatureSelected.connect(self.select_signature)
        self.pdf_view.deleteRequested.connect(self.delete_signature)
        self.pdf_view.scaleAdjustRequested.connect(self.adjust_signature_scale)
        self.pdf_view.previewPositionChanged.connect(self.update_preview_position)
        self.setCentralWidget(self.pdf_view)

        self.status_label = QLabel("Open a PDF to begin")
        self._build_toolbar()
        self.statusBar().addWidget(self.status_label)

        self.ensure_signature_path()
        self._push_preview_size_to_view()
        if initial_pdf_path:
            self.open_pdf(initial_pdf_path)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_button = QPushButton("Open")
        open_button.clicked.connect(self.open_pdf_dialog)
        toolbar.addWidget(open_button)

        save_as_button = QPushButton("Save As")
        save_as_button.clicked.connect(self.save_as)
        toolbar.addWidget(save_as_button)

        overwrite_button = QPushButton("Overwrite")
        overwrite_button.clicked.connect(self.save_overwrite)
        toolbar.addWidget(overwrite_button)

        change_sig_button = QPushButton("Change Signature")
        change_sig_button.clicked.connect(self.choose_signature)
        toolbar.addWidget(change_sig_button)

        zoom_out = QPushButton("-")
        zoom_out.clicked.connect(lambda: self.change_zoom(0.9))
        toolbar.addWidget(zoom_out)

        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(lambda: self.change_zoom(1.1))
        toolbar.addWidget(zoom_in)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Signature size"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setMinimum(20)
        self.scale_slider.setMaximum(300)
        self.scale_slider.setValue(int(self.signature_scale * 100))
        self.scale_slider.valueChanged.connect(self.on_scale_slider_changed)
        self.scale_slider.setFixedWidth(180)
        toolbar.addWidget(self.scale_slider)

        toolbar.addSeparator()
        self.mode_button = QPushButton("Placement: On")
        self.mode_button.clicked.connect(self.toggle_placement_mode)
        toolbar.addWidget(self.mode_button)

    def ensure_signature_path(self) -> None:
        if not self.config_manager.has_valid_signature(self.config):
            self.choose_signature(required=True)

    def choose_signature(self, required: bool = False) -> None:
        start_dir = self.config.last_open_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Choose signature PNG", start_dir, "PNG Files (*.png)")
        if path:
            self.config.signature_path = path
            self.config.last_open_dir = str(Path(path).parent)
            self.config_manager.save(self.config)
            self.status_label.setText(f"Signature: {Path(path).name}")
        elif required:
            QMessageBox.warning(self, "Signature required", "Please choose a PNG signature to continue.")

    def open_pdf_dialog(self) -> None:
        start_dir = self.config.last_open_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", start_dir, "PDF Files (*.pdf)")
        if path:
            self.open_pdf(path)

    def open_pdf(self, path: str) -> None:
        try:
            self.pdf_service.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return

        self.state = DocumentState(pdf_path=path, page_count=self.pdf_service.page_count(), zoom=self.state.zoom, signatures=[])
        self.config.last_open_dir = str(Path(path).parent)
        self.config_manager.save(self.config)
        self.render_document()
        self.status_label.setText(f"Opened {Path(path).name} ({self.state.page_count} pages)")

    def render_document(self) -> None:
        if not self.state.pdf_path:
            return

        pages = []
        for page_index in range(self.state.page_count):
            pdf_width, pdf_height = self.pdf_service.page_size(page_index)
            pixmap = self.pdf_service.render_page(page_index, self.state.zoom)
            pages.append((pixmap, pdf_width, pdf_height, self.state.zoom))

        self.pdf_view.set_pages(pages)
        self._push_preview_size_to_view()
        self.refresh_signatures()

    def refresh_signatures(self) -> None:
        for page_index in range(self.state.page_count):
            page_sigs = [sig for sig in self.state.signatures if sig.page_index == page_index]
            self.pdf_view.update_page_signatures(page_index, page_sigs, self.state.selected_signature_id, self.placing_enabled)

    def _signature_dimensions_pdf(self) -> tuple[float, float]:
        width = 140.0 * self.signature_scale
        height = width * 0.35
        return width, height

    def _push_preview_size_to_view(self) -> None:
        width, height = self._signature_dimensions_pdf()
        self.pdf_view.set_preview_size_pdf(width, height)

    def place_signature(self, page_index: int, pdf_x: float, pdf_y: float) -> None:
        if not self.config_manager.has_valid_signature(self.config):
            self.choose_signature(required=True)
            if not self.config_manager.has_valid_signature(self.config):
                return

        width, height = self._signature_dimensions_pdf()
        page_width, page_height = self.pdf_service.page_size(page_index)
        x = max(0.0, min(pdf_x - width / 2, page_width - width))
        y = max(0.0, min(pdf_y - height / 2, page_height - height))
        sig = PlacedSignature(
            page_index=page_index,
            x=x,
            y=y,
            width=width,
            height=height,
            image_path=self.config.signature_path,
            id=self.next_signature_id,
        )
        self.next_signature_id += 1
        self.state.signatures.append(sig)
        self.state.selected_signature_id = sig.id
        self.refresh_signatures()
        self.status_label.setText("Signature placed. Drag to reposition, Delete to remove.")

    def move_signature(self, page_index: int, signature_id: int, pdf_x: float, pdf_y: float) -> None:
        for sig in self.state.signatures:
            if sig.id == signature_id and sig.page_index == page_index:
                page_width, page_height = self.pdf_service.page_size(page_index)
                sig.x = max(0.0, min(pdf_x, page_width - sig.width))
                sig.y = max(0.0, min(pdf_y, page_height - sig.height))
                self.state.selected_signature_id = signature_id
                self.refresh_signatures()
                return

    def select_signature(self, signature_id: int) -> None:
        self.state.selected_signature_id = signature_id
        self.refresh_signatures()

    def delete_signature(self, signature_id: int) -> None:
        self.state.signatures = [sig for sig in self.state.signatures if sig.id != signature_id]
        if self.state.selected_signature_id == signature_id:
            self.state.selected_signature_id = None
        self.refresh_signatures()

    def on_scale_slider_changed(self, value: int) -> None:
        self.signature_scale = max(0.2, value / 100.0)
        self.config.default_scale = self.signature_scale
        self.config_manager.save(self.config)
        self._push_preview_size_to_view()
        self.status_label.setText(f"Signature scale: {self.signature_scale:.2f}x")

    def adjust_signature_scale(self, step: int) -> None:
        value = max(self.scale_slider.minimum(), min(self.scale_slider.maximum(), self.scale_slider.value() + step * 10))
        self.scale_slider.setValue(value)

    def toggle_placement_mode(self) -> None:
        self.placing_enabled = not self.placing_enabled
        self.mode_button.setText(f"Placement: {'On' if self.placing_enabled else 'Off'}")
        self.pdf_view.set_placing_enabled(self.placing_enabled)
        self.refresh_signatures()

    def update_preview_position(self, page_index: int, pdf_x: float, pdf_y: float) -> None:
        self.preview_page_index = page_index
        self.preview_pdf_x = pdf_x
        self.preview_pdf_y = pdf_y

    def change_zoom(self, factor: float) -> None:
        if not self.state.pdf_path:
            return
        self.state.zoom = max(0.5, min(3.0, self.state.zoom * factor))
        self.render_document()
        self.status_label.setText(f"Zoom: {self.state.zoom:.2f}x")

    def save_as(self) -> None:
        if not self.state.pdf_path:
            QMessageBox.information(self, "No PDF", "Open a PDF first.")
            return
        source = Path(self.state.pdf_path)
        default_name = source.with_name(f"{source.stem}-signed{source.suffix}")
        path, _ = QFileDialog.getSaveFileName(self, "Save signed PDF", str(default_name), "PDF Files (*.pdf)")
        if not path:
            return
        self._save_to_path(path)

    def save_overwrite(self) -> None:
        if not self.state.pdf_path:
            QMessageBox.information(self, "No PDF", "Open a PDF first.")
            return
        response = QMessageBox.question(
            self,
            "Overwrite original?",
            "This will replace the original PDF. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._save_to_path(self.state.pdf_path)

    def _save_to_path(self, path: str) -> None:
        try:
            self.pdf_service.save_with_signatures(path, self.state.signatures)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.status_label.setText(f"Saved {Path(path).name}")

    def closeEvent(self, event) -> None:
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self.config_manager.save(self.config)
        self.pdf_service.close()
        super().closeEvent(event)
