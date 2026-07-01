from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QToolBar,
    QVBoxLayout,
)

from .. import __build__, __version__
from ..config import ConfigManager
from ..models import AppConfig, DocumentState, PlacedStamp
from ..pdf_service import PDFDocumentService
from .pdf_view import PDFView


class TextStampSettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Text Stamp Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit(config.signer_name)
        self.city_input = QLineEdit(config.signer_city)
        self.date_format_input = QLineEdit(config.date_format)

        form.addRow("Signer name", self.name_input)
        form.addRow("Signer city", self.city_input)
        form.addRow("Date format", self.date_format_input)
        layout.addLayout(form)

        hint = QLabel("Date format uses Python strftime, for example: %Y-%m-%d")
        hint.setStyleSheet("color: #555;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str]:
        return (
            self.name_input.text().strip(),
            self.city_input.text().strip(),
            self.date_format_input.text().strip() or "%Y-%m-%d",
        )


class MainWindow(QMainWindow):
    MODE_SIGNATURE = "signature"
    MODE_DATE = "date"
    MODE_CITY = "city"
    MODE_NAME = "name"

    def __init__(self, config_manager: ConfigManager, initial_pdf_path: str | None = None) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.config: AppConfig = self.config_manager.load()
        self.pdf_service = PDFDocumentService()
        self.state = DocumentState(zoom=1.0)
        self.stamp_scale = max(0.2, self.config.default_scale)
        self.stamp_rotation = self.config.stamp_rotation % 360
        self.next_stamp_id = 1
        self.placing_enabled = True
        self.preview_page_index: int | None = None
        self.preview_pdf_x: float | None = None
        self.preview_pdf_y: float | None = None
        self.current_mode = self.MODE_SIGNATURE
        self.setWindowTitle(f"Signature Signer {__version__} ({__build__})")
        self.resize(self.config.window_width, self.config.window_height)

        self.pdf_view = PDFView()
        self.pdf_view.placementRequested.connect(self.place_stamp)
        self.pdf_view.stampMoved.connect(self.move_stamp)
        self.pdf_view.stampSelected.connect(self.select_stamp)
        self.pdf_view.deleteRequested.connect(self.delete_stamp)
        self.pdf_view.scaleAdjustRequested.connect(self.adjust_stamp_scale)
        self.pdf_view.previewPositionChanged.connect(self.update_preview_position)
        self.setCentralWidget(self.pdf_view)

        self.status_label = QLabel("Open a PDF to begin")
        self._build_toolbar()
        self.statusBar().addWidget(self.status_label)

        self.ensure_signature_path()
        self._push_preview_size_to_view()
        self._push_preview_payload_to_view()
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

        text_settings_button = QPushButton("Text Stamp Settings")
        text_settings_button.clicked.connect(self.open_text_settings)
        toolbar.addWidget(text_settings_button)

        zoom_out = QPushButton("-")
        zoom_out.clicked.connect(lambda: self.change_zoom(0.9))
        toolbar.addWidget(zoom_out)

        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(lambda: self.change_zoom(1.1))
        toolbar.addWidget(zoom_in)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Mode"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItem("Signature", self.MODE_SIGNATURE)
        self.mode_selector.addItem("Date", self.MODE_DATE)
        self.mode_selector.addItem("City", self.MODE_CITY)
        self.mode_selector.addItem("Name", self.MODE_NAME)
        self.mode_selector.currentIndexChanged.connect(self.on_mode_changed)
        toolbar.addWidget(self.mode_selector)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Stamp size"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setMinimum(20)
        self.scale_slider.setMaximum(300)
        self.scale_slider.setValue(int(self.stamp_scale * 100))
        self.scale_slider.valueChanged.connect(self.on_scale_slider_changed)
        self.scale_slider.setFixedWidth(180)
        toolbar.addWidget(self.scale_slider)

        self.rotate_button = QPushButton(f"Rotate: {self.stamp_rotation}°")
        self.rotate_button.clicked.connect(self.rotate_stamp)
        toolbar.addWidget(self.rotate_button)

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
            self._push_preview_payload_to_view()
            self.status_label.setText(f"Signature: {Path(path).name}")
        elif required:
            QMessageBox.warning(self, "Signature required", "Please choose a PNG signature to continue.")

    def open_text_settings(self) -> bool:
        dialog = TextStampSettingsDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        name, city, date_format = dialog.values()
        self.config.signer_name = name
        self.config.signer_city = city
        self.config.date_format = date_format
        self.config_manager.save(self.config)
        self._push_preview_payload_to_view()
        return True

    def _require_text_setting(self, field: str) -> bool:
        value = getattr(self.config, field, "").strip()
        if value:
            return True
        QMessageBox.information(self, "Missing value", "Please provide text stamp settings first.")
        if not self.open_text_settings():
            return False
        return bool(getattr(self.config, field, "").strip())

    def _stamp_text_for_mode(self, mode: str) -> str:
        if mode == self.MODE_DATE:
            try:
                return datetime.now().strftime(self.config.date_format or "%Y-%m-%d")
            except Exception:
                return datetime.now().strftime("%Y-%m-%d")
        if mode == self.MODE_CITY:
            return self.config.signer_city.strip()
        if mode == self.MODE_NAME:
            return self.config.signer_name.strip()
        return ""

    def _stamp_dimensions_pdf(self) -> tuple[float, float]:
        if self.current_mode == self.MODE_SIGNATURE:
            width = 140.0 * self.stamp_scale
            height = width * 0.35
            return width, height

        width = 180.0 * self.stamp_scale
        height = 26.0 * self.stamp_scale
        return width, height

    def _push_preview_size_to_view(self) -> None:
        width, height = self._stamp_dimensions_pdf()
        self.pdf_view.set_preview_size_pdf(width, height)

    def _push_preview_payload_to_view(self) -> None:
        text = self._stamp_text_for_mode(self.current_mode)
        self.pdf_view.set_preview_payload(self.current_mode, text, self.config.signature_path, self.stamp_rotation)

    def on_mode_changed(self) -> None:
        self.current_mode = self.mode_selector.currentData()
        if self.current_mode == self.MODE_CITY and not self._require_text_setting("signer_city"):
            self.mode_selector.setCurrentIndex(0)
            self.current_mode = self.MODE_SIGNATURE
        elif self.current_mode == self.MODE_NAME and not self._require_text_setting("signer_name"):
            self.mode_selector.setCurrentIndex(0)
            self.current_mode = self.MODE_SIGNATURE

        self._push_preview_size_to_view()
        self._push_preview_payload_to_view()
        self.status_label.setText(f"Mode: {self.current_mode.title()}")

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

        self.state = DocumentState(pdf_path=path, page_count=self.pdf_service.page_count(), zoom=self.state.zoom, stamps=[])
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
        self._push_preview_payload_to_view()
        self.refresh_stamps()

    def refresh_stamps(self) -> None:
        for page_index in range(self.state.page_count):
            page_stamps = [stamp for stamp in self.state.stamps if stamp.page_index == page_index]
            self.pdf_view.update_page_stamps(page_index, page_stamps, self.state.selected_stamp_id, self.placing_enabled)

    def place_stamp(self, page_index: int, pdf_x: float, pdf_y: float) -> None:
        if self.current_mode == self.MODE_SIGNATURE and not self.config_manager.has_valid_signature(self.config):
            self.choose_signature(required=True)
            if not self.config_manager.has_valid_signature(self.config):
                return

        if self.current_mode == self.MODE_CITY and not self._require_text_setting("signer_city"):
            return
        if self.current_mode == self.MODE_NAME and not self._require_text_setting("signer_name"):
            return

        width, height = self._stamp_dimensions_pdf()
        page_width, page_height = self.pdf_service.page_size(page_index)
        x = max(0.0, min(pdf_x - width / 2, page_width - width))
        y = max(0.0, min(pdf_y - height / 2, page_height - height))

        stamp = PlacedStamp(
            page_index=page_index,
            x=x,
            y=y,
            width=width,
            height=height,
            kind=self.current_mode,
            image_path=self.config.signature_path if self.current_mode == self.MODE_SIGNATURE else "",
            text=self._stamp_text_for_mode(self.current_mode),
            rotation=self.stamp_rotation,
            id=self.next_stamp_id,
        )
        self.next_stamp_id += 1
        self.state.stamps.append(stamp)
        self.state.selected_stamp_id = stamp.id
        self.refresh_stamps()
        self.status_label.setText("Stamp placed. Drag to reposition, Delete to remove.")

    def move_stamp(self, page_index: int, stamp_id: int, pdf_x: float, pdf_y: float) -> None:
        for stamp in self.state.stamps:
            if stamp.id == stamp_id and stamp.page_index == page_index:
                page_width, page_height = self.pdf_service.page_size(page_index)
                stamp.x = max(0.0, min(pdf_x, page_width - stamp.width))
                stamp.y = max(0.0, min(pdf_y, page_height - stamp.height))
                self.state.selected_stamp_id = stamp_id
                self.refresh_stamps()
                return

    def select_stamp(self, stamp_id: int) -> None:
        self.state.selected_stamp_id = stamp_id
        self.refresh_stamps()

    def delete_stamp(self, stamp_id: int) -> None:
        self.state.stamps = [stamp for stamp in self.state.stamps if stamp.id != stamp_id]
        if self.state.selected_stamp_id == stamp_id:
            self.state.selected_stamp_id = None
        self.refresh_stamps()

    def on_scale_slider_changed(self, value: int) -> None:
        self.stamp_scale = max(0.2, value / 100.0)
        self.config.default_scale = self.stamp_scale
        self.config_manager.save(self.config)
        self._push_preview_size_to_view()
        self._push_preview_payload_to_view()
        if self.preview_page_index is not None and self.preview_pdf_x is not None and self.preview_pdf_y is not None:
            self.pdf_view.set_preview_position_pdf(self.preview_page_index, self.preview_pdf_x, self.preview_pdf_y)
        self.status_label.setText(f"Stamp scale: {self.stamp_scale:.2f}x")

    def adjust_stamp_scale(self, step: int) -> None:
        value = max(self.scale_slider.minimum(), min(self.scale_slider.maximum(), self.scale_slider.value() + step * 10))
        self.scale_slider.setValue(value)

    def rotate_stamp(self) -> None:
        self.stamp_rotation = (self.stamp_rotation + 90) % 360
        self.config.stamp_rotation = self.stamp_rotation
        self.config_manager.save(self.config)
        self.rotate_button.setText(f"Rotate: {self.stamp_rotation}°")
        self._push_preview_payload_to_view()
        self.status_label.setText(f"Stamp rotation: {self.stamp_rotation}°")

    def toggle_placement_mode(self) -> None:
        self.placing_enabled = not self.placing_enabled
        self.mode_button.setText(f"Placement: {'On' if self.placing_enabled else 'Off'}")
        self.pdf_view.set_placing_enabled(self.placing_enabled)
        self.refresh_stamps()

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
            self.pdf_service.save_with_stamps(path, self.state.stamps)
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
