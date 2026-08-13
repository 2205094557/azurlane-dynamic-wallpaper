"""静态立绘提取插件：调用 azur-paint main2 完整图层合成引擎。

azur-paint（krazete，无 LICENSE 标注）为成熟实现，集成时注明出处。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import UnityPy
from PIL import Image

from core.locks import named_lock
from core.registry import ExtractorPlugin

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"


def _root_dir() -> Path:
    """定位项目根（打包版为 _internal，开发版为项目根）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


ROOT = _root_dir()
AZP_MAIN2 = ROOT / "references" / "azur-paint" / "main2.py"
# azur-paint 通过 os.chdir + 全局 sys.argv 运行（进程级状态），
# 并发下载时多个线程会互相踩踏 cwd/argv 导致合成失败回退到简单拼接，必须串行化。
# 锁名与 live2d 提取、后端 run_tool 共用：它们都改全局 sys.argv，必须同一把 OS 级锁
# （打包版可能同时从 PYZ/磁盘导入本模块形成多实例，模块级 threading.Lock 不共享）。
_AZP_LOCK = named_lock("azurlane_sysargv")


def _run_azur_paint(painting: str, bundles: Path, out_name: str, dest: Path) -> bool:
    """在进程内运行 azur-paint main2.py（打包版无法起子进程），产物直接写入 dest。"""
    if not AZP_MAIN2.exists():
        return False
    sys.path.insert(0, str(AZP_MAIN2.parent))
    with _AZP_LOCK:
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as td:
                os.chdir(td)
                sys.argv = ["main2.py", "-p", painting, "-d", str(bundles), "-o", out_name, "-f", "-1"]
                try:
                    import runpy

                    runpy.run_path(str(AZP_MAIN2), run_name="__main__")
                finally:
                    os.chdir(old_cwd)
                src = Path(td) / "output2" / f"{out_name}.png"
                if src.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    return True
        except Exception as e:  # noqa: BLE001
            print(f"[static] azur-paint 引擎失败: {e}")
        finally:
            sys.argv = old_argv
    return False


def get_dependencies(dependencies_path: str) -> dict:
    """解析 dependencies 包：painting 文件 → 依赖的 tex 文件列表。"""
    import re

    env = UnityPy.load(dependencies_path)
    bundle = None
    for asset in env.assets:
        for value in asset.values():
            if value.type.name == "AssetBundle":
                bundle = value
                break
    if bundle is None:
        return {}
    tree = bundle.read_typetree()
    container = tree.get("m_Container") or []
    if not container:
        return {}
    primary = env.assets[0].objects[container[0][1]["asset"]["m_PathID"]].read_typetree()
    deps = {}
    for m_value in primary.get("m_Values", []):
        fname = m_value.get("m_FileName", "")
        m = re.search(r"/(painting/[^/]+)$", fname)
        if m:
            deps[m.group(1)] = m_value.get("m_Dependencies", [])
    return deps


def _stitch_simple(mesh, texture):
    """兜底：单网格单纹理的三角形缝合。"""
    lines = mesh.export().splitlines()
    draw_pic, tex_pos, faces = [], [], []
    for line in lines:
        if line.startswith("v "):
            p = line.split()
            draw_pic.append((int(float(p[1])), int(float(p[2]))))
        elif line.startswith("vt "):
            p = line.split()
            tex_pos.append((float(p[1]), float(p[2])))
        elif line.startswith("f "):
            p = line.split()
            if len(p) >= 4:
                faces.append([int(p[i].split("/")[0]) for i in range(1, 4)])
    if not faces or not draw_pic:
        return None
    w, h = texture.m_Width, texture.m_Height
    tex_px = [(round(u * w), round((1 - v) * h)) for u, v in tex_pos]
    img = texture.image
    xmin = min(x for x, y in draw_pic)
    xmax = max(x for x, y in draw_pic)
    ymin = min(y for x, y in draw_pic)
    ymax = max(y for x, y in draw_pic)
    flipped = [(x - xmin, ymax - y) for x, y in draw_pic]
    canvas = Image.new("RGBA", (xmax - xmin, ymax - ymin), (255, 255, 255, 0))
    for face in faces:
        try:
            i0, i1, i2 = face
            pts = [flipped[i0 - 1], flipped[i1 - 1], flipped[i2 - 1]]
            cuts = [tex_px[i0 - 1], tex_px[i1 - 1], tex_px[i2 - 1]]
            px = min(p[0] for p in pts)
            py = min(p[1] for p in pts)
            cut = img.crop(
                (
                    min(c[0] for c in cuts),
                    min(c[1] for c in cuts),
                    max(c[0] for c in cuts),
                    max(c[1] for c in cuts),
                )
            )
            canvas.paste(cut, (px, py))
        except Exception:  # noqa: BLE001
            continue
    return canvas


def _get_mesh_texture(tex_path):
    mesh = texture = None
    env = UnityPy.load(str(tex_path))
    for asset in env.assets:
        for value in asset.values():
            if value.type.name == "Mesh":
                mesh = value.read()
            elif value.type.name == "Texture2D":
                texture = value.read()
    return mesh, texture


class StaticExtractor(ExtractorPlugin):
    id = "static"
    name = "静态立绘提取"

    def extract(
        self,
        prefab_path: str,
        tex_path: str,
        out_dir: str,
        dependencies_path: str | None = None,
        root: Path | None = None,
    ) -> dict:
        painting = Path(prefab_path).name
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        bundles = (root or ROOT) / "resources" / "bundles"

        # 主路径：azur-paint main2 完整图层合成
        if AZP_MAIN2.exists() and (bundles / "dependencies").exists():
            try:
                if _run_azur_paint(painting, bundles, "painting_tmp", out / "painting.png"):
                    return {"image": "painting.png", "size": list(Image.open(out / "painting.png").size), "mode": "azur-paint"}
            except Exception as e:  # noqa: BLE001
                print(f"[static] azur-paint 引擎失败: {e}")

        # 兜底：单网格单纹理
        mesh, texture = _get_mesh_texture(tex_path)
        if mesh and texture:
            canvas = _stitch_simple(mesh, texture)
            if canvas is not None:
                canvas.save(out / "painting.png")
                return {"image": "painting.png", "size": list(canvas.size), "mode": "simple"}
        if texture:
            texture.image.save(out / "painting.png")
            return {"image": "painting.png", "size": list(texture.image.size), "mode": "direct"}
        raise RuntimeError("未找到可用的网格或贴图")
