# -*- coding: utf-8 -*-
"""打包版发布前全链路验收。

覆盖：health → 下载 static/live2d/spine → 检查提取产物完整（合成图 / model3.json / skel）
→ 三种导出 → 检查导出项目关键文件 → 清理测试数据（可选）。
任一环节失败即非零退出，不允许交付。

用法：
  python tools/verify_package.py                 # 验收（复用已运行的 8770 或自动启动 exe）
  python tools/verify_package.py --clean          # 验收通过后清空测试下载并重启软件
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

API = "http://127.0.0.1:8770"
ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "azurlane-wallpaper"
EXE = DIST / "azurlane-wallpaper.exe"
INTERNAL = DIST / "_internal"


def api(path: str, payload: dict | None = None, timeout: int = 300) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(name: str, ok: bool, extra: str = "") -> bool:
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + extra) if extra else ""))
    return ok


def wait_health(exe: Path, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if api("/api/health", timeout=5).get("ok"):
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise RuntimeError("打包版后端 8770 未就绪")


def image_size(png: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(png) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None


def verify() -> bool:
    ok = True
    health = api("/api/health")
    ok = check("health：插件齐全", bool(health.get("ok")), json.dumps(health.get("plugins", {}), ensure_ascii=False))

    # 1) 静态立绘：必须走 azur-paint 合成（尺寸接近 2048 级，而不是原始贴图碎片）
    r = api("/api/download", {"ship": "2B", "bundle": ""})
    png = INTERNAL / "resources" / "extracted" / "static" / "2b" / "painting.png"
    size = image_size(png) if png.exists() else None
    ok = check(
        "静态下载+合成 painting.png",
        bool(r.get("ok")) and png.exists() and size is not None and min(size) >= 1000,
        f"{png.name} {size}",
    ) and ok

    # 2) Live2D：必须完整转换（model3.json + moc3 + 动作）
    r = api("/api/download", {"ship": "Z23", "bundle": ""})
    model = INTERNAL / "resources" / "extracted" / "live2d" / "z23" / "Z23" / "Z23.model3.json"
    moc = INTERNAL / "resources" / "extracted" / "live2d" / "z23" / "Z23" / "Z23.moc3"
    anims = list((INTERNAL / "resources" / "extracted" / "live2d" / "z23" / "Z23" / "Animation").glob("*.motion3.json")) if (INTERNAL / "resources" / "extracted" / "live2d" / "z23" / "Z23" / "Animation").exists() else []
    ok = check(
        "L2D 下载+完整模型",
        bool(r.get("ok")) and model.exists() and moc.exists() and len(anims) >= 10,
        f"model3/moc3 存在，动作 {len(anims)} 个",
    ) and ok

    # 3) Spine：skel + atlas + 贴图
    r = api("/api/download", {"ship": "2B", "bundle": "_2"})
    skel = INTERNAL / "resources" / "extracted" / "spine" / "2b_2" / "2B_2.skel"
    atlas = INTERNAL / "resources" / "extracted" / "spine" / "2b_2" / "2B_2.atlas"
    ok = check(
        "Spine 下载+提取",
        bool(r.get("ok")) and skel.exists() and atlas.exists(),
        "skel/atlas 存在",
    ) and ok

    # 4) 三种导出
    opts = {"bg": "monet", "scale": 100, "offsetX": 0, "offsetY": 0, "alignment": "center"}
    r = api("/api/export", {"ship": "2B", "bundle": "", "options": opts})
    proj = Path(r.get("project", ""))
    ok = check(
        "静态导出",
        bool(r.get("ok")) and (proj / "assets" / "painting.png").exists(),
        str(proj),
    ) and ok

    r = api("/api/export", {"ship": "Z23", "bundle": "", "options": opts})
    proj = Path(r.get("project", ""))
    ok = check(
        "L2D 导出",
        bool(r.get("ok"))
        and (proj / "live2dcubismcore.min.js").exists()
        and any(proj.rglob("*.model3.json")),
        str(proj),
    ) and ok

    r = api("/api/export", {"ship": "2B", "bundle": "_2", "options": opts})
    proj = Path(r.get("project", ""))
    ok = check(
        "Spine 导出",
        bool(r.get("ok")) and (proj / "spine-webgl-3.8.js").exists() and list((proj / "assets").glob("*.png")),
        str(proj),
    ) and ok

    # 5) 并发下载：并发与串行产物必须一致（防 chdir/sys.argv 竞争导致拼接错乱/卡死）
    conc_targets = [("Z23", "_5", "z23_5"), ("Z23", "_6", "z23_6"), ("Z23", "_7", "z23_7"), ("Z23", "_10", "z23_10")]
    import concurrent.futures

    def dl(item):
        ship, bundle, painting = item
        api("/api/download", {"ship": ship, "bundle": bundle})
        png = INTERNAL / "resources" / "extracted" / "static" / painting / "painting.png"
        return painting, png.stat().st_size if png.exists() else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        conc = dict(pool.map(dl, conc_targets))
    serial = {}
    for ship, bundle, painting in conc_targets:
        api("/api/download", {"ship": ship, "bundle": bundle})
        png = INTERNAL / "resources" / "extracted" / "static" / painting / "painting.png"
        serial[painting] = png.stat().st_size if png.exists() else None
    mismatch = [p for p in conc if conc.get(p) != serial.get(p) or not conc.get(p)]
    ok = check(
        "并发下载产物与串行一致（4 个静态皮肤）",
        not mismatch,
        f"不一致: {mismatch} 并发={conc} 串行={serial}",
    ) and ok

    return ok


def clean() -> None:
    """清空运行时下载数据，恢复“全新安装”状态（只动运行时目录，不动头像/元数据）。"""
    for sub in ("bundles", "extracted", "wallpapers", "exports"):
        d = INTERNAL / "resources" / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    ls = INTERNAL / "resources" / "metadata" / "local_skins.json"
    ls.write_text("[]", encoding="utf-8")
    print("  已清理测试下载数据（bundles/extracted/wallpapers/exports，local_skins.json 重置为空）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(DIST))
    ap.add_argument("--clean", action="store_true", help="验收通过后清空测试数据并重启软件")
    args = ap.parse_args()

    exe = Path(args.dist) / "azurlane-wallpaper.exe"
    print(f"验收对象：{exe}")
    # 先清掉任何残留的旧打包版实例（8770/5174 可能被旧进程占用，
    # 不杀会导致验收复用旧实例而验错对象 → 假 PASS）
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process -Name azurlane-wallpaper -ErrorAction SilentlyContinue | Stop-Process -Force"],
        check=False,
    )
    time.sleep(2)
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    wait_health(exe)

    ok = verify()
    print()
    if not ok:
        print("验收失败：不允许交付。")
        return 1
    print("验收通过：下载/提取/导出全链路正常，可以交付。")

    if args.clean:
        # 清空需先停掉软件（文件被占用）
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
        else:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process -Name azurlane-wallpaper -ErrorAction SilentlyContinue | Stop-Process -Force"],
                check=False,
            )
            time.sleep(2)
        clean()
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        wait_health(exe)
        print("已重启软件（干净状态）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
