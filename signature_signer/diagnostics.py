from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any

import fitz

PACKAGES = ("PyMuPDF", "PyQt6", "PyQt6-Qt6", "PyQt6-sip")


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def page_geometry(path: Path) -> dict[str, Any]:
    doc = fitz.open(path)
    try:
        pages: list[dict[str, Any]] = []
        for index, page in enumerate(doc):
            images: list[dict[str, Any]] = []
            for image in page.get_images(full=True):
                xref = image[0]
                rects = [list(rect) for rect in page.get_image_rects(xref)]
                images.append({"xref": xref, "rects": rects})
            pages.append(
                {
                    "index": index,
                    "rotation": page.rotation,
                    "rect": list(page.rect),
                    "cropbox": list(page.cropbox),
                    "mediabox": list(page.mediabox),
                    "transformation_matrix": list(page.transformation_matrix),
                    "rotation_matrix": list(page.rotation_matrix),
                    "derotation_matrix": list(page.derotation_matrix),
                    "image_count": len(images),
                    "images": images,
                }
            )
        return {"path": str(path), "page_count": len(doc), "pages": pages}
    finally:
        doc.close()


def build_report(pdf_paths: list[Path]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": package_versions(),
        "fitz_doc": fitz.__doc__,
        "fitz_version": getattr(fitz, "version", None),
        "pdfs": [],
    }
    for path in pdf_paths:
        report["pdfs"].append(page_geometry(path))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print PDF Signature Signer environment and optional PDF geometry diagnostics."
    )
    parser.add_argument("pdf", nargs="*", type=Path, help="Optional original/signed PDFs to inspect")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = [str(path) for path in args.pdf if not path.is_file()]
    if missing:
        raise SystemExit(f"PDF file not found: {', '.join(missing)}")
    print(json.dumps(build_report(args.pdf), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
