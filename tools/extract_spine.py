"""从 spinepainting `_res` Bundle 提取 Spine 三件套（.skel/.atlas/贴图）。

用法: python tools/extract_spine.py <bundle_path> <out_dir>
"""

import sys
from pathlib import Path

import UnityPy


def extract(bundle_path: str, out_dir: str) -> None:
    src = Path(bundle_path)
    dst = Path(out_dir)
    dst.mkdir(parents=True, exist_ok=True)

    env = UnityPy.load(str(src))
    n_skel = n_atlas = n_tex = 0
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
                n_skel += 1
            elif name.endswith(".atlas"):
                n_atlas += 1
            print(f"  TextAsset -> {name} ({len(data.m_Script)} bytes)")
        elif tname == "Texture2D":
            data = obj.read()
            name = (data.m_Name or f"texture_{obj.path_id}") + ".png"
            img = data.image
            if img is None:
                print(f"  Texture2D {name}: 解码失败（格式 {data.m_TextureFormat}）")
                continue
            img.save(dst / name)
            n_tex += 1
            print(f"  Texture2D -> {name} ({img.width}x{img.height})")

    print(f"完成: skel={n_skel} atlas={n_atlas} texture={n_tex} -> {dst}")


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
