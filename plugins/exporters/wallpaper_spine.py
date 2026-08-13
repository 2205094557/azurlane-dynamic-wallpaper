"""Spine 壁纸导出插件：生成 WE web 壁纸项目（base64 内嵌骨架 + 多贴图）。"""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path

from core.registry import ExporterPlugin
from core.wallpaper import (
    SPINE_RUNTIME,
    WALLPAPER_LAYOUT,
    bg_css_for_skin,
    export_defaults,
    project_dir_name,
    project_json,
    render_template,
)


class WallpaperSpineExporter(ExporterPlugin):
    id = "wallpaper_spine"
    name = "Spine 壁纸导出"

    def export(self, skin: dict, options: dict, out_dir: str) -> str:
        out = Path(out_dir)
        proj = out / project_dir_name(skin["ship"], skin["name"])
        assets = proj / "assets"
        assets.mkdir(parents=True, exist_ok=True)

        src_dir = Path(options["root"]) / "resources" / skin["asset"]["dir"]
        shutil.copy2(SPINE_RUNTIME, proj / "spine-webgl-3.8.js")
        shutil.copy2(WALLPAPER_LAYOUT, proj / "wallpaper-layout.js")

        layers = []
        for layer in skin["asset"]["layers"]:
            skel = (src_dir / layer["skel"]).read_bytes()
            atlas_text = (src_dir / layer["atlas"]).read_text(encoding="utf-8")
            pages = re.findall(r"^([^\r\n]+\.png)\s*$", atlas_text, re.M)
            textures = []
            for page in pages:
                shutil.copy2(src_dir / page, assets / page)
                textures.append({"page": page, "file": "assets/" + page})
            layers.append({
                "name": layer["skel"].replace(".skel", ""),
                "skelData": base64.b64encode(skel).decode("ascii"),
                "atlasText": atlas_text,
                "textures": textures,
            })

        html = render_template(
            "wallpaper_spine.html",
            LAYERS_JSON=json.dumps(layers, ensure_ascii=False),
            TITLE=f"{skin['ship']} · {skin['name']}",
            BG_CSS=bg_css_for_skin(
                skin, options.get("root"), options.get("bg", "monet"), options.get("bgColor")
            ),
            **export_defaults(options),
        )
        (proj / "index.html").write_text(html, encoding="utf-8")
        (proj / "project.json").write_text(
            json.dumps(
                project_json(
                    f"{skin['ship']} · {skin['name']}",
                    scale=options.get("scale", 100),
                    offset_x=options.get("offsetX", 0),
                    offset_y=options.get("offsetY", 0),
                    alignment=options.get("alignment", 0),
                    animations=options.get("animations") or [],
                    animation=options.get("animation") or "",
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(proj)
