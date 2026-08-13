"""元数据服务：读取 resources/metadata（bwiki 同步的官方数据 + 本地资源索引）。"""

from __future__ import annotations

import json
from pathlib import Path


class Metadata:
    def __init__(self, metadata_dir: Path) -> None:
        self.dir = Path(metadata_dir)
        self._ships: list[dict] = []
        self._skins: list[dict] = []
        self._local: list[dict] = []
        self.reload()

    def reload(self) -> None:
        self._ships = self._read("ships.json", [])
        self._skins = self._read("skins.json", [])
        self._local = self._read("local_skins.json", [])

    def _read(self, name: str, default):
        p = self.dir / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return default

    def ships(self) -> list[dict]:
        return self._ships

    def skins(self) -> list[dict]:
        return self._skins

    def local_skins(self) -> list[dict]:
        return self._local

    def skin_type(self, ship: str, bundle: str) -> str | None:
        for loc in self._local:
            if loc.get("ship") == ship and loc.get("bundle") == bundle:
                return loc.get("type")
        return None