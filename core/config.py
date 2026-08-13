"""应用配置：resources/config.json（不存在则用默认值）。"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "proxy": "",
    "concurrency": 4,
    "download_dir": "resources/bundles",
    "extract_dir": "resources/extracted",
}


class Config:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data = dict(DEFAULTS)
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )