# -*- coding: utf-8 -*-
"""打包后的程序入口：内置后端 API + 静态前端服务器 + pywebview 窗口。"""
import ctypes
import json
import os
import socket
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import webview

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "frontend" / "dist"
RESOURCES = ROOT / "resources"
BACKEND_PORT = 8770
STATIC_PORT = 5174

# 用户级持久化：窗口尺寸/最大化 + WebView2 localStorage（收藏、音量、并发数等设置）
APP_DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "azurlane-dynamic-wallpaper"
PREFS_FILE = APP_DATA / "prefs.json"
WEBVIEW_DATA = APP_DATA / "webview"
DEFAULT_SIZE = (1380, 860)
MIN_SIZE = (1000, 640)


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
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
        sw = int(user32.GetSystemMetrics(0) / scale)
        sh = int(user32.GetSystemMetrics(1) / scale)
        return max(0, (sw - width) // 2), max(0, (sh - height) // 2)
    except Exception:  # noqa: BLE001
        return None, None


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # 必须先解码 URL（中文头像文件名会被浏览器转义）；query 参数不参与文件定位；
        # 保留 / 语义做归一化，防目录穿越
        path = unquote(path.split("?", 1)[0]).replace("\\", "/")
        if path.startswith("/"):
            path = path[1:]
        parts = [p for p in path.split("/") if p not in ("", ".", "..")]
        rel = "/".join(parts)
        base = RESOURCES if rel.startswith("resources/") else DIST
        if rel.startswith("resources/"):
            rel = rel[len("resources/"):]
        full = (base / rel).resolve()
        base_res = base.resolve()
        if str(full).startswith(str(base_res)):
            return str(full)
        return str(base_res)

    def end_headers(self):
        # 静态资源统一禁用浏览器缓存：local_skins.json 等在下载/提取后即时更新，
        # 若浏览器读到旧缓存会一直显示"未下载"、预览出不来。
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def ensure_runtime_dirs() -> None:
    """打包版从空状态开始：初始化本地下载索引与运行时目录。"""
    (RESOURCES / "metadata").mkdir(parents=True, exist_ok=True)
    ls = RESOURCES / "metadata" / "local_skins.json"
    if not ls.exists():
        ls.write_text("[]", encoding="utf-8")
    for sub in ("bundles", "extracted", "wallpapers", "exports"):
        (RESOURCES / sub).mkdir(parents=True, exist_ok=True)


def main() -> None:
    ensure_runtime_dirs()
    # 后端 API（8766）
    if not port_open(BACKEND_PORT):
        import backend_server

        threading.Thread(target=backend_server.main, args=(BACKEND_PORT,), daemon=True).start()
    # 静态前端（5174，服务 frontend/dist + resources/）
    server = ThreadingHTTPServer(("127.0.0.1", STATIC_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{STATIC_PORT}/"
    prefs = load_prefs()
    width = max(MIN_SIZE[0], int(prefs.get("width", DEFAULT_SIZE[0])))
    height = max(MIN_SIZE[1], int(prefs.get("height", DEFAULT_SIZE[1])))
    x, y = centered_position(width, height)

    window = webview.create_window(
        "碧蓝航线动态壁纸工具",
        url,
        width=width,
        height=height,
        x=x,
        y=y,
        min_size=MIN_SIZE,
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
        if save_timer:
            save_timer.cancel()
        save_timer = threading.Timer(0.5, lambda: persist(lambda p: p.update(last_size)))
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

    # private_mode=False + 固定 storage_path：localStorage（音量/线程数/收藏等）跨重启保留
    webview.start(debug=False, private_mode=False, storage_path=str(WEBVIEW_DATA))


if __name__ == "__main__":
    main()
