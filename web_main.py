"""桌面入口：pywebview 窗口加载前端（开发模式加载 Vite dev server）。

持久化约定：
  - WebView2 数据目录（localStorage/收藏）固定到 %APPDATA%\\azurlane-dynamic-wallpaper\\webview
  - 窗口尺寸 / 最大化状态保存到 %APPDATA%\\azurlane-dynamic-wallpaper\\prefs.json
"""

import json
import os
import sys
import threading
import ctypes
from pathlib import Path

import webview

from web_backend import WebApi

DEV_URL = "http://127.0.0.1:5173"
APP_DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "azurlane-dynamic-wallpaper"
PREFS_FILE = APP_DATA / "prefs.json"
WEBVIEW_DATA = APP_DATA / "webview"
DEFAULT_SIZE = (1380, 860)
MIN_SIZE = (1000, 640)


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_prefs(prefs: dict) -> None:
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        PREFS_FILE.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[prefs] save failed: {e}")


def centered_position(width: int, height: int) -> tuple[int | None, int | None]:
    """计算主屏幕居中的逻辑像素坐标（pywebview 的 CenterScreen 在部分环境不生效）。"""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        dpi = user32.GetDpiForSystem() or 96
        scale = dpi / 96.0
        # DPI-aware 下 GetSystemMetrics 返回物理像素，换算回逻辑像素
        sw = int(user32.GetSystemMetrics(0) / scale)
        sh = int(user32.GetSystemMetrics(1) / scale)
        return max(0, (sw - width) // 2), max(0, (sh - height) // 2)
    except Exception:  # noqa: BLE001
        return None, None


def main() -> None:
    api = WebApi()
    url = DEV_URL if len(sys.argv) < 2 else sys.argv[1]
    prefs = load_prefs()
    width = max(MIN_SIZE[0], int(prefs.get("width", DEFAULT_SIZE[0])))
    height = max(MIN_SIZE[1], int(prefs.get("height", DEFAULT_SIZE[1])))
    maximized = bool(prefs.get("maximized", False))
    x, y = centered_position(width, height)

    window = webview.create_window(
        "碧蓝航线动态壁纸工具",
        url,
        js_api=api,
        width=width,
        height=height,
        x=x,
        y=y,
        min_size=MIN_SIZE,
        maximized=maximized,
    )

    last_size = {"width": width, "height": height}
    save_lock = threading.Lock()
    save_timer = None

    def is_valid_size(w: int, h: int) -> bool:
        return w >= MIN_SIZE[0] and h >= MIN_SIZE[1]

    def persist(mutate=None) -> None:
        nonlocal save_timer
        with save_lock:
            p = {k: v for k, v in load_prefs().items() if k in ("width", "height", "maximized")}
            if mutate:
                mutate(p)
            save_prefs(p)

    def on_resized(w: int, h: int) -> None:
        nonlocal save_timer, last_size
        if not is_valid_size(w, h):
            return
        last_size = {"width": w, "height": h}
        # 拖拽缩放时事件很频繁，节流到 500ms 写一次
        if save_timer:
            save_timer.cancel()
        save_timer = threading.Timer(
            0.5,
            lambda: persist(lambda p: p.update(last_size)),
        )
        save_timer.daemon = True
        save_timer.start()

    def on_maximized() -> None:
        persist(lambda p: p.update({**last_size, "maximized": True}))

    def on_restored() -> None:
        try:
            w, h = window.width, window.height
            if is_valid_size(w, h):
                last_size.update({"width": w, "height": h})
        except Exception:  # noqa: BLE001
            pass
        persist(lambda p: p.update({**last_size, "maximized": False}))

    def on_closing() -> None:
        if save_timer:
            save_timer.cancel()
        persist(lambda p: p.update(last_size))

    window.events.resized += on_resized
    window.events.maximized += on_maximized
    window.events.restored += on_restored
    window.events.closing += on_closing

    # private_mode=False + 固定 storage_path：localStorage（收藏等）跨重启保留
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=str(WEBVIEW_DATA),
    )


if __name__ == "__main__":
    main()
