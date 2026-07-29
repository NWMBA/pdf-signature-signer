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


def _write_leaky_transform_pdf(path: Path) -> None:
    """Create a PDF whose content stream leaves a flipped CTM active.

    Some office/Google Docs exports use an initial vertical flip transform. The
    flattened save path must not append stamps into that transform context; it
    should render the visible page first and then draw the visible stamp pixels.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((1, 1), "placeholder")
    doc.save(path)
    doc.close()

    doc = fitz.open(path)
    page = doc[0]
    xref = page.get_contents()[0]
    doc.update_stream(
        xref,
        b"1 0 0 -1 0 792 cm\nBT /helv 24 Tf 60 60 Td (Leaky CTM top text) Tj ET\n",
    )
    doc.saveIncr()
    doc.close()


def _count_red_edges(rendered: fitz.Pixmap, x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    red_left = red_right = red_top = red_bottom = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            offset = (y * rendered.width + x) * 3
            r, g, b = rendered.samples[offset : offset + 3]
            if r > 200 and g < 80 and b < 80:
                local_x = x - x0
                local_y = y - y0
                red_left += int(local_x < 20)
                red_right += int(local_x >= (x1 - x0) - 20)
                red_top += int(local_y < 10)
                red_bottom += int(local_y >= (y1 - y0) - 10)
    return red_left, red_right, red_top, red_bottom


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
    assert image_rects == [doc[0].rect]

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


def test_save_with_stamps_preserves_selectable_text_with_full_page_overlay(tmp_path: Path) -> None:
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
    assert "Top marker" in doc[0].get_text("text")
    image_rects = doc[0].get_image_rects(doc[0].get_images(full=True)[-1][0])
    assert image_rects == [doc[0].rect]
    rendered = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    red_pixels = 0
    for y in range(126, 166):
        for x in range(460, 580):
            offset = (y * rendered.width + x) * 3
            r, g, b = rendered.samples[offset : offset + 3]
            red_pixels += int(r > 200 and g < 80 and b < 80)
    assert red_pixels > 0
    doc.close()


def test_save_with_stamps_flattens_output_for_leaky_page_transforms(tmp_path: Path) -> None:
    _skip_without_qt_image_support()
    pdf_path = tmp_path / "leaky.pdf"
    output_path = tmp_path / "signed.pdf"
    signature_path = tmp_path / "signature.png"
    _write_leaky_transform_pdf(pdf_path)
    _write_test_signature(signature_path)

    service = PDFDocumentService()
    service.open(str(pdf_path))
    service.save_with_stamps(
        str(output_path),
        [
            PlacedStamp(
                page_index=0,
                x=83,
                y=168,
                width=120,
                height=40,
                kind="signature",
                image_path=str(signature_path),
            )
        ],
    )
    service.close()

    doc = fitz.open(output_path)
    assert len(doc[0].get_images(full=True)) == 1
    assert doc[0].get_image_rects(doc[0].get_images(full=True)[0][0]) == [doc[0].rect]
    rendered = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    red_left, red_right, red_top, red_bottom = _count_red_edges(rendered, 83, 168, 203, 208)
    assert red_left > red_right
    assert red_bottom > red_top
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
