"""Spine 提取插件：从 spinepainting `_res` bundle 提取 .skel/.atlas/贴图。"""

from __future__ import annotations

from pathlib import Path

import UnityPy

from core.registry import ExtractorPlugin

# 碧蓝航线部分新皮肤包（如 2B/A2 的 spinepainting/2b_2）Unity 版本字段是占位符
# "0.0.0"，UnityPy 无法自动识别；统一回退到游戏实际使用的 Unity 版本即可解析。
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.51f1"


class SpineExtractor(ExtractorPlugin):
    id = "spine"
    name = "Spine 提取器"

    def extract(self, bundle_path: str, out_dir: str) -> dict:
        src = Path(bundle_path)
        dst = Path(out_dir)
        dst.mkdir(parents=True, exist_ok=True)
        env = UnityPy.load(str(src))
        result = {"skel": [], "atlas": [], "textures": []}
        for obj in env.objects:
            tname = obj.type.name
            if tname == "TextAsset":
                data = obj.read()
                name = data.m_Name or f"textasset_{obj.path_id}"
                script = data.m_Script
                if isinstance(script, str):
                    script = script.encode("utf-8", "surrogateescape")
                (dst / name).write_bytes(script)
                if name.endswith(".skel"):
                    result["skel"].append(name)
                elif name.endswith(".atlas"):
                    result["atlas"].append(name)
            elif tname == "Texture2D":
                data = obj.read()
                name = (data.m_Name or f"texture_{obj.path_id}") + ".png"
                img = data.image
                if img is None:
                    continue
                img.save(dst / name)
                result["textures"].append(name)
        return result
