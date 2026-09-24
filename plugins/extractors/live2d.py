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


def _enable_unitypy_boost() -> bool:
    """启用 UnityPy 的 C 扩展类型树解析（UnityPyBoost）。

    UnityPyLive2DExtractor 源码里有一行 `TypeTreeHelper.read_typetree_boost = False`
    主动禁用了该扩展（该设置是历史遗留，实测开启后输出与纯 Python 实现逐字节一致）。
    纯 Python 逐字节解析是提取耗时的大头：读 5635 个 MonoBehaviour
    15.3s → 0.13s，整个 Live2D 转换 79.5s → 20.4s（约 4 倍）。

    这里在导入转换器之后把开关打开（而不是改第三方源码——references/ 不入库，
    改它换机器/更新依赖即失效）。C 扩展缺失时静默跳过，行为退回原样，不影响正确性。
    """
    try:
        from UnityPy.helpers import TypeTreeHelper
        from UnityPy.UnityPyBoost import read_typetree as _boost

        TypeTreeHelper.read_typetree_boost = _boost
        return True
    except Exception:  # noqa: BLE001
        return False


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

            # 转换器模块级有一行 `read_typetree_boost = False`（首次导入时执行），
            # 必须在 import 之后再启用一次，否则开关会被它覆盖回纯 Python 实现。
            _enable_unitypy_boost()
            l2d_main.__main__()
        finally:
            sys.argv = old_argv


def _clean_textures(dst: Path) -> None:
    """清掉贴图透明像素的灰色 RGB（Live2D 部件边缘灰缝）。

    纯 PIL 实现（不引 numpy，省约 27MB 打包体积）：
    以 alpha==0 为掩码把 RGB 乘 0，alpha 通道原样保留。
    说明：
      - 已干净的图直接跳过重写，避免无谓的 PNG 重新编码；
      - 提取产物里同一张贴图常存两份（根目录 + Textures/ 子目录），
        按「文件大小 + 尺寸」判定重复，重复的只清一次并直接复制结果，
        省掉一半的大图解码/编码开销（4096² 贴图单张约 0.7s）。
    """
    try:
        from PIL import Image, ImageChops

        done: dict[tuple[int, tuple[int, int]], Path] = {}  # (size, dims) -> 已清理的文件
        for png in Path(dst).rglob("*.png"):
            try:
                stat = png.stat()
                with Image.open(png) as src:
                    size_key = (stat.st_size, src.size)
                    im = src.convert("RGBA")
                prev = done.get(size_key)
                if prev is not None:
                    # 同尺寸同字节数的贴图视作同一张：直接复用已清理结果
                    try:
                        shutil.copyfile(prev, png)
                        continue
                    except Exception:  # noqa: BLE001
                        pass  # 复制失败则回退到正常处理
                alpha = im.getchannel("A")
                if alpha.getextrema()[0] > 0:
                    continue  # 全是非透明像素，无需处理
                # keep_mask：255=保留 RGB（alpha!=0），0=清零 RGB（alpha==0）
                # 用查找表（比逐像素 lambda 快，4096² 图上差异明显）
                keep_mask = alpha.point([0] + [255] * 255).convert("RGB")
                rgb = im.convert("RGB")
                cleaned = ImageChops.multiply(rgb, keep_mask)
                if ImageChops.difference(rgb, cleaned).getbbox() is None:
                    continue  # 本来就是干净的，保持原文件字节不变
                out = cleaned.convert("RGBA")
                out.putalpha(alpha)
                out.save(png)
                done[size_key] = png
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
