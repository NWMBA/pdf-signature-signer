from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from signature_signer.models import PlacedStamp
from signature_signer.pdf_geometry import displayed_rect_to_pdf_rect
from signature_signer.pdf_service import PDFDocumentService, signature_image_bytes_for_pdf


def _write_test_signature(path: Path) -> None:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 40), False)
    pix.clear_with(255)
    for y in range(40):
        for x in range(120):
            if x < 10 or y > 30:
                pix.set_pixel(x, y, (255, 0, 0))
            elif 30 < x < 90 and 10 < y < 25:
                pix.set_pixel(x, y, (0, 0, 255))
    pix.save(path)


def _write_rotated_pdf(path: Path, rotation: int = 180) -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 60), "Top marker")
    page.insert_text((60, 730), "Bottom marker")
    page.set_rotation(rotation)
    doc.save(path)
    doc.close()


def _skip_without_qt_image_support() -> None:
    try:
        from PyQt6.QtGui import QImageReader  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"Qt image support unavailable in this environment: {exc}")


def test_displayed_rect_maps_to_unrotated_pdf_rect_for_rotate_180(tmp_path: Path) -> None:
    pdf_path = tmp_path / "rotated.pdf"
    _write_rotated_pdf(pdf_path, rotation=180)

    doc = fitz.open(pdf_path)
    page = doc[0]
    displayed_rect = fitz.Rect(60, 680, 180, 720)

    mapped = displayed_rect_to_pdf_rect(page, displayed_rect)

    assert mapped == fitz.Rect(432, 72, 552, 112)
    doc.close()


def test_save_with_stamps_honors_display_coordinates_on_rotated_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "rotated.pdf"
    output_path = tmp_path / "signed.pdf"
    signature_path = tmp_path / "signature.png"
    _write_rotated_pdf(pdf_path, rotation=180)
    _write_test_signature(signature_path)

    service = PDFDocumentService()
    service.open(str(pdf_path))
    service.save_with_stamps(
        str(output_path),
        [
            PlacedStamp(
                page_index=0,
                x=60,
                y=680,
                width=120,
                height=40,
                kind="signature",
                image_path=str(signature_path),
            )
        ],
    )
    service.close()

    doc = fitz.open(output_path)
    image_rects = doc[0].get_image_rects(doc[0].get_images(full=True)[0][0])
    assert image_rects == [fitz.Rect(432, 72, 552, 112)]

    rendered = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    red_left = red_right = red_top = red_bottom = 0
    for y in range(680, 720):
        for x in range(60, 180):
            offset = (y * rendered.width + x) * 3
            r, g, b = rendered.samples[offset : offset + 3]
            if r > 200 and g < 80 and b < 80:
                local_x = x - 60
                local_y = y - 680
                red_left += int(local_x < 20)
                red_right += int(local_x >= 100)
                red_top += int(local_y < 10)
                red_bottom += int(local_y >= 30)
    assert red_left > red_right
    assert red_bottom > red_top
    doc.close()


def test_signature_image_bytes_for_pdf_bakes_manual_rotation(tmp_path: Path) -> None:
    _skip_without_qt_image_support()
    signature_path = tmp_path / "signature.png"
    _write_test_signature(signature_path)

    normalized_doc = fitz.open("png", signature_image_bytes_for_pdf(str(signature_path), rotation=180))
    pix = normalized_doc[0].get_pixmap(alpha=False)

    red_left = red_right = red_top = red_bottom = 0
    for y in range(pix.height):
        for x in range(pix.width):
            offset = (y * pix.width + x) * 3
            r, g, b = pix.samples[offset : offset + 3]
            if r > 200 and g < 80 and b < 80:
                red_left += int(x < 20)
                red_right += int(x >= pix.width - 20)
                red_top += int(y < 10)
                red_bottom += int(y >= pix.height - 10)

    assert red_right > red_left
    assert red_top > red_bottom
    normalized_doc.close()


def test_save_with_stamps_bakes_signature_rotation_before_pdf_insert(tmp_path: Path) -> None:
    _skip_without_qt_image_support()
    pdf_path = tmp_path / "unrotated.pdf"
    output_path = tmp_path / "signed.pdf"
    signature_path = tmp_path / "signature.png"
    _write_rotated_pdf(pdf_path, rotation=0)
    _write_test_signature(signature_path)

    service = PDFDocumentService()
    service.open(str(pdf_path))
    service.save_with_stamps(
        str(output_path),
        [
            PlacedStamp(
                page_index=0,
                x=60,
                y=680,
                width=120,
                height=40,
                kind="signature",
                image_path=str(signature_path),
                rotation=180,
            )
        ],
    )
    service.close()

    doc = fitz.open(output_path)
    rendered = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    red_left = red_right = red_top = red_bottom = 0
    for y in range(680, 720):
        for x in range(60, 180):
            offset = (y * rendered.width + x) * 3
            r, g, b = rendered.samples[offset : offset + 3]
            if r > 200 and g < 80 and b < 80:
                local_x = x - 60
                local_y = y - 680
                red_left += int(local_x < 20)
                red_right += int(local_x >= 100)
                red_top += int(local_y < 10)
                red_bottom += int(local_y >= 30)
    assert red_right > red_left
    assert red_top > red_bottom
    doc.close()


def test_save_with_stamps_keeps_top_left_display_coordinates_on_unrotated_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "unrotated.pdf"
    output_path = tmp_path / "signed.pdf"
    signature_path = tmp_path / "signature.png"
    _write_rotated_pdf(pdf_path, rotation=0)
    _write_test_signature(signature_path)

    service = PDFDocumentService()
    service.open(str(pdf_path))
    service.save_with_stamps(
        str(output_path),
        [
            PlacedStamp(
                page_index=0,
                x=460,
                y=126,
                width=120,
                height=40,
                kind="signature",
                image_path=str(signature_path),
            )
        ],
    )
    service.close()

    doc = fitz.open(output_path)
    image_rects = doc[0].get_image_rects(doc[0].get_images(full=True)[0][0])
    assert image_rects == [fitz.Rect(460, 126, 580, 166)]
    doc.close()


def test_save_with_stamps_can_overwrite_original_without_incremental_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "original.pdf"
    signature_path = tmp_path / "signature.png"
    _write_rotated_pdf(pdf_path, rotation=0)
    _write_test_signature(signature_path)

    service = PDFDocumentService()
    service.open(str(pdf_path))
    service.save_with_stamps(
        str(pdf_path),
        [
            PlacedStamp(
                page_index=0,
                x=60,
                y=680,
                width=120,
                height=40,
                kind="signature",
                image_path=str(signature_path),
            )
        ],
    )

    assert service.doc is not None
    assert service.page_count() == 1
    service.close()

    doc = fitz.open(pdf_path)
    assert len(doc[0].get_images(full=True)) == 1
    doc.close()
