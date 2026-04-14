# PDF Signature Signer

A lightweight, local-first Linux desktop app for visually signing PDFs with a stored PNG signature.

Important: this app places a signature image onto a PDF. It does **not** create a cryptographic or certificate-based digital signature.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt6 PyMuPDF
python3 -m signature_signer /path/to/file.pdf
```

## Features

- Local-first, no network access
- Stores a reusable signature PNG path in `~/.config/signature_signer/config.json`
- Opens PDFs from CLI argument or file picker
- Scrollable multi-page PDF view
- Live signature preview under cursor
- Resize signature with slider or mouse wheel while placing
- Drag placed signatures before saving
- Delete selected signatures before saving
- Save As by default, overwrite only with confirmation

## Linux Mint `.desktop` file

Save this as `~/.local/share/applications/signature-signer.desktop`:

```ini
[Desktop Entry]
Version=1.0
Type=Application
Name=Signature Signer
Comment=Sign PDFs with a stored PNG signature
Exec=python3 -m signature_signer %f
Icon=accessories-text-editor
Terminal=false
Categories=Office;Utility;
MimeType=application/pdf;
StartupNotify=true
NoDisplay=false
```

Then run:

```bash
update-desktop-database ~/.local/share/applications
```
