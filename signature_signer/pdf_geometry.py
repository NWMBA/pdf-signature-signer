from __future__ import annotations

import fitz


def displayed_rect_to_pdf_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """Map a rectangle from the rendered/displayed page space to PDF space.

    PyMuPDF renders pages with their /Rotate value applied, so mouse coordinates
    captured from the viewer are in the displayed page coordinate system. Write
    operations such as insert_image / insert_textbox operate in unrotated PDF
    coordinates. On rotated pages (especially /Rotate 180), using displayed
    coordinates directly places stamps on the opposite side and visually rotates
    them with the page.
    """
    pdf_rect = fitz.Rect(rect) * page.derotation_matrix
    pdf_rect.normalize()
    return pdf_rect
