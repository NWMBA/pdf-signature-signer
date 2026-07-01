from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    signature_path: str = ""
    signer_name: str = ""
    signer_city: str = ""
    date_format: str = "%Y-%m-%d"
    last_open_dir: str = str(Path.home())
    default_scale: float = 1.0
    stamp_rotation: int = 0
    wheel_scale_step: float = 0.1
    window_width: int = 1200
    window_height: int = 900


@dataclass
class PlacedStamp:
    page_index: int
    x: float
    y: float
    width: float
    height: float
    kind: str
    image_path: str = ""
    text: str = ""
    rotation: int = 0
    id: int = field(default=0)


@dataclass
class DocumentState:
    pdf_path: Optional[str] = None
    page_count: int = 0
    zoom: float = 1.0
    stamps: list[PlacedStamp] = field(default_factory=list)
    selected_stamp_id: Optional[int] = None
