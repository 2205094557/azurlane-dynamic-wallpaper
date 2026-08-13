"""Live2D 提取插件：从 live2d bundle 提取 Cubism 模型。

完整转换依赖 UnityPyLive2DExtractor（参考实现位于 references/UnityPyLive2DExtractor），
本插件会自动调用它；不可用时退化为原始资源导出。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import UnityPy

from core.locks import named_lock
from core.registry import ExtractorPlugin

# 部分 bundle 不含 Unity 版本头，必须显式指定 fallback，否则 UnityPy 直接抛错
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

# UnityPyLive2DExtractor 通过全局 sys.argv 运行（进程级状态），并发下载时需串行化。
# 与 azur-paint、后端 run_tool 共用同一把 OS 级锁（它们都改全局 sys.argv）。
_L2D_LOCK = named_lock("azurlane_sysargv")


def _ref_root() -> Path:
    """定位 references 目录（打包版在 _internal/references，开发版在项目根）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "references"
    return Path(__file__).resolve().parents[2] / "references"


def _run_live2d_extractor(src: Path, dst: Path, ref: Path) -> None:
    """在进程内运行 UnityPyLive2DExtractor（打包版无法起子进程）。"""
    if not (ref / "UnityPyLive2DExtractor" / "__main__.py").exists():
        return
    sys.path.insert(0, str(ref))
    with _L2D_LOCK:
        old_argv = sys.argv
        sys.argv = ["UnityPyLive2DExtractor", str(src), str(dst), "--log-level", "ERROR"]
        try:
            import UnityPyLive2DExtractor.__main__ as l2d_main

            l2d_main.__main__()
        finally:
            sys.argv = old_argv


def _clean_textures(dst: Path) -> None:
    """清掉贴图透明像素的灰色 RGB（Live2D 部件边缘灰缝）。"""
    try:
        import numpy as np
        from PIL import Image

        for png in Path(dst).rglob("*.png"):
            try:
                im = Image.open(png).convert("RGBA")
                arr = np.array(im)
                arr[arr[:, :, 3] == 0] = 0
                Image.fromarray(arr).save(png)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _patch_model3(model3: Path) -> None:
    """给 model3.json 补上动作引用（pixi 读取 FileReferences.Motions）。"""
    if not model3.exists():
        return
    data = json.loads(model3.read_text(encoding="utf-8"))
    anim_src = None
    for p in [model3.parent, *model3.parent.parents]:
        cand = p / "Animation"
        if cand.is_dir():
            anim_src = cand
            break
    if anim_src is None or "Motions" in data.get("FileReferences", {}):
        return
    anim_dir = model3.parent / "Animation"
    if anim_src.resolve() != anim_dir.resolve() and not anim_dir.exists():
        shutil.copytree(anim_src, anim_dir)
    motions: dict[str, list] = {}
    for f in sorted(anim_dir.glob("*.motion3.json")):
        name = f.stem.replace(".motion3", "")
        group = "Idle" if name.startswith("idle") or name in ("normal", "home") else "Tap"
        motions.setdefault(group, []).append(
            {"File": f"Animation/{f.name}", "FadeInTime": 0.5, "FadeOutTime": 0.5}
        )
    if motions:
        data["Motions"] = motions
        data.setdefault("FileReferences", {})["Motions"] = motions
        model3.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Live2DExtractor(ExtractorPlugin):
    id = "live2d"
    name = "Live2D 提取器"

    def extract(self, bundle_path: str, out_dir: str) -> dict:
        src = Path(bundle_path)
        dst = Path(out_dir)
        dst.mkdir(parents=True, exist_ok=True)

        env = UnityPy.load(str(src))
        for obj in env.objects:
            tname = obj.type.name
            if tname == "TextAsset":
                data = obj.read()
                name = data.m_Name or f"textasset_{obj.path_id}"
                script = data.m_Script
                if isinstance(script, str):
                    script = script.encode("utf-8", "surrogateescape")
                (dst / name).write_bytes(script)
            elif tname == "Texture2D":
                data = obj.read()
                name = (data.m_Name or f"texture_{obj.path_id}") + ".png"
                img = data.image
                if img is not None:
                    img.save(dst / name)

        # 完整转换：调用参考实现 UnityPyLive2DExtractor
        ref = _ref_root() / "UnityPyLive2DExtractor"
        if ref.exists():
            try:
                _run_live2d_extractor(src, dst, ref)
            except Exception as e:  # noqa: BLE001
                print("[live2d] UnityPyLive2DExtractor error:", e)
            # 补动作引用（模型可能在子目录）
            for m3 in dst.rglob("*.model3.json"):
                _patch_model3(m3)

        _clean_textures(dst)
        return {"files": sorted(p.name for p in dst.iterdir())}
