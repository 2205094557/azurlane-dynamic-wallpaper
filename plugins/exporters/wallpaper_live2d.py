"""Live2D 壁纸导出插件：生成 WE web 壁纸项目（pixi + Cubism 运行时）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.registry import ExporterPlugin
from core.wallpaper import (
    L2D_APP,
    L2D_CORE,
    WALLPAPER_LAYOUT,
    bg_css_for_skin,
    export_defaults,
    project_dir_name,
    project_json,
    render_template,
)


class WallpaperLive2DExporter(ExporterPlugin):
    id = "wallpaper_live2d"
    name = "Live2D 壁纸导出"

    def export(self, skin: dict, options: dict, out_dir: str) -> str:
        out = Path(out_dir)
        proj = out / project_dir_name(skin["ship"], skin["name"])
        model_dir = proj / "assets" / "model"
        model_dir.mkdir(parents=True, exist_ok=True)

        src_dir = Path(options["root"]) / "resources" / skin["asset"]["dir"]
        # 复制模型目录全部文件（model3.json/moc3/贴图/动作）
        for f in src_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src_dir)
                dst = model_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)

        shutil.copy2(L2D_CORE, proj / "live2dcubismcore.min.js")
        shutil.copy2(L2D_APP, proj / "live2d-app.js")
        shutil.copy2(WALLPAPER_LAYOUT, proj / "wallpaper-layout.js")

        cfg = {"model": "assets/model/" + skin["asset"]["model"]}
        html = render_template(
            "wallpaper_live2d.html",
            L2D_CONFIG_JSON=json.dumps(cfg, ensure_ascii=False),
            BG_CSS=bg_css_for_skin(
                skin, options.get("root"), options.get("bg", "monet"), options.get("bgColor")
            ),
            L2D_ANIM=options.get("animation", "") or "",
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
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(proj)
