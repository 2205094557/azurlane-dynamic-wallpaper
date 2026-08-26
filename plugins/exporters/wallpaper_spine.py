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
        has_login = False
        for layer in skin["asset"]["layers"]:
            skel = (src_dir / layer["skel"]).read_bytes()
            # 自动检测 login 动画：直接在 skel 二进制里搜动画名字符串
            # （比运行时解析轻量；碧蓝 skel 动画名以可读 ASCII 存储）
            if b"login" in skel:
                has_login = True
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

        # 互动语音：开关开启且本地有该船语音时复制进壁纸并注入运行时配置
        voice_on = bool(options.get("voice", True))
        voice_cfg = None
        if voice_on:
            try:
                from core import voice as voice_mod
                ship_id = voice_mod.ship_id_for(skin.get("painting", ""))
                if ship_id:
                    voice_cfg = voice_mod.export_voice(ship_id, proj / "assets" / "voice")
            except Exception:  # noqa: BLE001
                voice_cfg = None

        # 开场动画：仅皮肤有 login 动画时提供（自动检测）；关闭时不播入场直接待机
        intro_on = bool(options.get("intro", True)) and has_login
        # 互动开关（点击/拖拽触发动画反应）
        interact_on = bool(options.get("interact", True))

        # 交互区域数据：从参考数据集（游戏 prefab 提取的碰撞框）拉取，
        # 内嵌进壁纸（离线可用）；失败则空（壁纸隐藏交互区域开关无效果但不报错）。
        # 注意：必须直连（禁用系统代理）——本机代理会拦截该数据站返回 403。
        hit_areas = []
        interact_rules = []
        try:
            import urllib.parse as _up
            import urllib.request as _req

            painting = skin.get("painting", "")
            # 无代理 opener：系统代理（127.0.0.1:xxxx）会拦截数据站返回 403
            opener = _req.build_opener(_req.ProxyHandler({}))
            opener.addheaders = [("User-Agent", "Mozilla/5.0")]

            def _get_json(url: str):
                with opener.open(url, timeout=10) as resp:
                    return json.load(resp)

            model_data = _get_json(f"https://data.nagami.moe/spine/models/{_up.quote(painting)}.json")
            if isinstance(model_data.get("hitAreas"), list):
                hit_areas = model_data["hitAreas"]

            # 官方点击互动规则（config_client）：asset → id → skins/{id}.json。
            # 规则语义：当前待机(idle)下点击(hit) → 播 action → 切 change_idle 循环
            #（如 携心夜烛 touch_special 播完进 touch_special_normal 特殊待机）。
            try:
                idx = _get_json("https://data.nagami.moe/spine/index.json")
                skin_id = next((s.get("id") for s in idx.get("skins", []) if s.get("asset") == painting), None)
                if skin_id:
                    skin_cfg = _get_json(f"https://data.nagami.moe/spine/skins/{_up.quote(str(skin_id))}.json")
                    cc = ((skin_cfg.get("interaction") or {}).get("drag_data") or {}).get("config_client")
                    if isinstance(cc, list):
                        interact_rules = [r for r in cc if isinstance(r, dict)]
            except Exception as e:  # noqa: BLE001
                print(f"[spine] 互动规则拉取失败（降级为轮换互动）: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[spine] 交互区域数据拉取失败（降级为无区域）: {e}")

        html = render_template(
            "wallpaper_spine.html",
            LAYERS_JSON=json.dumps(layers, ensure_ascii=False),
            TITLE=f"{skin['ship']} · {skin['name']}",
            BG_CSS=bg_css_for_skin(
                skin, options.get("root"), options.get("bg", "monet"), options.get("bgColor")
            ),
            VOICE_JSON=json.dumps(voice_cfg, ensure_ascii=False) if voice_cfg else "null",
            VOICE="true" if voice_on else "false",
            INTRO="true" if intro_on else "false",
            INTERACT="true" if interact_on else "false",
            HIT_AREAS_JSON=json.dumps(hit_areas, ensure_ascii=False),
            INTERACT_RULES_JSON=json.dumps(interact_rules, ensure_ascii=False),
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
                    spine=True,
                    voice=voice_on,
                    intro=intro_on,
                    interact=bool(options.get("interact", True)),
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(proj)
