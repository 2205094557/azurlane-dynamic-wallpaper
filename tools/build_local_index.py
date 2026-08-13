# -*- coding: utf-8 -*-
"""扫描 resources/extracted → 生成 local_skins.json（自动标记本地已提取皮肤）。

对照 skins.json 的 painting 字段，把提取目录映射为 (ship, bundle, name, type, asset)。
同名多部件皮肤（云龙-溶于重重夜色 = yunlong_2 + yunlong_3）会把部件文件合并到
主部件目录，并合成图层（背景在前、角色在后），让预览/导出作为一个皮肤渲染。
"""
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "resources" / "metadata"
EXTRACTED = ROOT / "resources" / "extracted"

PARTS = ("T", "B", "M", "F")
# 变体骨架（换装/贴图等）不参与渲染
VARIANT_SUFFIXES = ("_hx", "_n", "_tex", "_res", "_rw", "_bj")


def parts_of(skin: dict) -> list[str]:
    return skin.get("parts") or [skin.get("painting", "")]


def stem_matches(stem: str, part: str) -> bool:
    """骨架文件名是否属于某个部件：{part}、{part}_bg（背景）、{part}_T/B/M/F。"""
    low = stem.lower()
    p = part.lower()
    if low == p or low == p + "_bg":
        return True
    return any(low == p + t.lower() or low == p + "_" + t.lower() for t in PARTS)


def collect_layers(pd: Path, all_parts: list[str]) -> list[dict]:
    layers = []
    for sk in sorted(pd.glob("*.skel")):
        stem = sk.stem
        low = stem.lower()
        if any(v in low for v in VARIANT_SUFFIXES):
            continue
        if not any(stem_matches(stem, p) for p in all_parts):
            continue
        atlas = pd / (stem + ".atlas")
        if atlas.exists():
            layers.append({"skel": sk.name, "atlas": atlas.name})
    # 背景骨架排最前（先渲染），其余保持字典序
    layers.sort(key=lambda l: (0 if l["skel"].lower().endswith("_bg.skel") else 1, l["skel"]))
    return layers


def live2d_asset(painting: str):
    d = EXTRACTED / "live2d" / painting
    if not d.is_dir():
        return None
    m3 = next(d.rglob("*.model3.json"), None)
    if not m3:
        return None
    return {"dir": "extracted/" + m3.parent.relative_to(EXTRACTED).as_posix(), "model": m3.name}


def main():
    skins = json.loads((MD / "skins.json").read_text(encoding="utf-8"))
    by_painting = {}
    for s in skins:
        for p in parts_of(s):
            if p and p not in by_painting:
                by_painting[p] = s

    local = []

    # spine 目录：按 skin 条目聚合部件，合并到主目录并合成图层
    spine_dir = EXTRACTED / "spine"
    if spine_dir.is_dir():
        by_entry: dict[tuple, dict] = {}
        for d in sorted(spine_dir.iterdir()):
            if not d.is_dir():
                continue
            info = by_painting.get(d.name)
            if not info:
                continue
            key = (info["ship"], info["bundle"], info["name"])
            by_entry.setdefault(key, info)
        for (ship, bundle, name), info in by_entry.items():
            present = [p for p in parts_of(info) if (spine_dir / p).is_dir()]
            if not present:
                continue
            # 高序号部件（背景/特效）在前，低序号（角色主体）在后置顶
            present_sorted = sorted(present, key=lambda p: p.lower(), reverse=True)
            primary = present[0]
            primary_dir = spine_dir / primary
            for p in present_sorted:
                pd = spine_dir / p
                if p != primary:
                    for f in pd.iterdir():
                        if f.is_file() and not (primary_dir / f.name).exists():
                            shutil.copy2(f, primary_dir / f.name)
            layers = []
            seen = set()
            for p in present_sorted:
                for layer in collect_layers(spine_dir / p, parts_of(info)):
                    if layer["skel"] not in seen:
                        seen.add(layer["skel"])
                        layers.append(layer)
            if layers:
                local.append({
                    "ship": ship, "bundle": bundle, "name": name,
                    "type": "spine", "painting": info.get("painting", primary),
                    "asset": {"dir": f"extracted/spine/{primary}", "layers": layers},
                })

    # live2d 目录
    l2d_dir = EXTRACTED / "live2d"
    if l2d_dir.is_dir():
        for d in sorted(l2d_dir.iterdir()):
            if not d.is_dir():
                continue
            info = by_painting.get(d.name)
            if not info:
                continue
            asset = live2d_asset(d.name)
            if not asset:
                continue
            local.append({
                "ship": info["ship"], "bundle": info["bundle"], "name": info["name"],
                "type": info["type"], "painting": info.get("painting", ""), "asset": asset,
            })

    # 静态立绘目录
    static_dir = EXTRACTED / "static"
    if static_dir.is_dir():
        for d in sorted(static_dir.iterdir()):
            if not d.is_dir():
                continue
            info = by_painting.get(d.name)
            if not info:
                continue
            png = d / "painting.png"
            if not png.exists():
                continue
            local.append({
                "ship": info["ship"], "bundle": info["bundle"], "name": info["name"],
                "type": "static",
                "painting": info.get("painting", ""),
                "asset": {"dir": f"extracted/static/{d.name}", "image": "painting.png"},
            })

    local.sort(key=lambda x: (x["ship"], x["bundle"]))
    (MD / "local_skins.json").write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    print("local_skins:", len(local))
    for l in local:
        print(" ", l["ship"], "|", l["bundle"], "|", l["name"], "|", l["type"], "|", l["asset"]["dir"])


if __name__ == "__main__":
    main()
