"""前端调用后端的中枢（M1 阶段实现完整 API）。"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class WebApi:
    """通过 window.pywebview.api 暴露给前端的方法。"""

    def ping(self) -> str:
        return "pong"

    # ---- 目录（桌面端无需本地后端服务即可打开）----
    def open_download_dir(self) -> dict:
        os.startfile(str(ROOT / "resources" / "bundles"))  # noqa: S606
        return {"ok": True}

    def open_extracted_dir(self) -> dict:
        os.startfile(str(ROOT / "resources" / "extracted"))  # noqa: S606
        return {"ok": True}

    # ---- 资源库 ----
    def list_ships(self) -> list:
        raise NotImplementedError("M1")

    def list_skins(self, ship_id: int) -> list:
        raise NotImplementedError("M1")

    # ---- 提取 ----
    def start_download(self, bundle_name: str) -> dict:
        raise NotImplementedError("M0")

    def extract_spine(self, bundle_path: str) -> dict:
        raise NotImplementedError("M0")

    def extract_live2d(self, bundle_path: str) -> dict:
        raise NotImplementedError("M0")

    # ---- 导出 ----
    def export_wallpaper(self, skin_id: int, options: dict) -> dict:
        raise NotImplementedError("M2")
