"""JSON persistence of user settings (record dialog defaults)."""

import json
from pathlib import Path


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def save(self, settings: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(settings, indent=2))
