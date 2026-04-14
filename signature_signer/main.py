"""
Quick Start

python3 -m venv .venv
source .venv/bin/activate
pip install PyQt6 PyMuPDF

Run:
python3 -m signature_signer.main /path/to/file.pdf
"""

from __future__ import annotations

import argparse
import sys

from PyQt6.QtWidgets import QApplication

from .config import ConfigManager
from .ui.main_window import MainWindow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visually sign PDFs with a stored PNG signature")
    parser.add_argument("pdf", nargs="?", help="Path to a PDF file to open")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app = QApplication(sys.argv)
    window = MainWindow(ConfigManager(), initial_pdf_path=args.pdf)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
