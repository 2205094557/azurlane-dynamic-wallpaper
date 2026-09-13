"""pywebview 桥：仅保留桌面端无需本地后端服务即可使用的方法，其余功能走 HTTP API。"""

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
