from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import AppConfig


CONFIG_DIR = Path.home() / ".config" / "signature_signer"
CONFIG_PATH = CONFIG_DIR / "config.json"


class ConfigManager:
    def load(self) -> AppConfig:
        if not CONFIG_PATH.exists():
            return AppConfig()

        try:
            data = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return AppConfig()

        config = AppConfig()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config

    def save(self, config: AppConfig) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2))

    def has_valid_signature(self, config: AppConfig) -> bool:
        return bool(config.signature_path) and Path(config.signature_path).is_file()
