# -*- coding: utf-8 -*-
"""增量更新元数据：检测官方 CDN 新增皮肤并合并 bwiki 皮肤名。

数据源：
- 官方 CDN hash 清单（paintinghash / l2dhash / azhash）：服务器当前全部立绘资源名
- B站 wiki 舰船页：皮肤中文名与顺序
- 本地 official/ship_skin_template.json：基础 painting（按前缀归属新皮肤）

流程：
1. 收集 CDN 立绘名，过滤变体（_tex/_res/_rw/_bj/_n/_hx/_dark_shadow 等）
2. 减去本地 skins.json 已有 painting → 候选新皮肤
3. 按舰船基础 painting 前缀归属（不区分大小写，要求剩余部分为 _数字）
4. 对命中舰船抓 bwiki 页面，按标题顺序匹配皮肤名
5. 无歧义时追加最小条目到 official 表并重建元数据；歧义项列出待人工确认

用法:
  python tools/update_metadata.py            # dry-run，只打印将新增/待确认
  python tools/update_metadata.py --apply    # 实际写入并重建
  python tools/update_metadata.py --ship 普利茅斯 --apply
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "resources" / "metadata"
OFF_SKIN = MD / "official" / "ship_skin_template.json"

WIKI_API = "https://wiki.biligame.com/blhx/api.php"
WIKI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SKIN_PREFIXES = ("painting/", "live2d/", "spinepainting/")

# 变体后缀/标记：这些不是独立皮肤
VARIANT_MARKERS = (
    "_tex", "_res", "_rw", "_bj", "_n_", "_hx", "_dark_shadow",
)
VARIANT_END = ("_n", "_hx")


def norm_name(name: str) -> str:
    """皮肤名归一化：去掉【誓约】等括号前缀与空白，避免新旧命名差异误判。"""
    n = re.sub(r"^【[^】]*】", "", name or "").strip()
    return n


def wiki_api(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=WIKI_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 1.5)
    return {}


def wiki_skin_names(ship: str) -> list[str]:
    """返回 bwiki 页面 标题N 字段（按 N 排序）。"""
    data = wiki_api({"action": "parse", "page": ship, "prop": "wikitext"})
    wt = data.get("parse", {}).get("wikitext", "")
    titles = re.findall(r"^\|\s*标题(\d+)\s*=\s*(.+)$", wt, re.M)
    titles.sort(key=lambda x: int(x[0]))
    return [t[1].strip() for t in titles]


def cdn_paintings() -> set[str]:
    """抓取 CDN 清单，返回全部立绘名；同时刷新 live2d/spine 类型清单。"""
    sys.path.insert(0, str(ROOT))
    from core.registry import Registry

    registry = Registry(ROOT / "plugins").discover()
    cdn = registry.get("sources", "cdn")
    info = cdn.handshake("CN")
    out: set[str] = set()
    live2d: set[str] = set()
    spine: set[str] = set()
    for key in ("paintinghash", "l2dhash", "azhash"):
        csv = cdn.fetch_hash_csv(info.cdn, info.raw_strings[key])
        for line in csv.splitlines():
            parts = line.split(",")
            if len(parts) >= 1:
                name = parts[0].strip().lower()
                for pref in SKIN_PREFIXES:
                    if name.startswith(pref):
                        bare = name[len(pref):]
                        out.add(bare)
                        if pref == "live2d/":
                            live2d.add(bare)
                        elif pref == "spinepainting/":
                            spine.add(bare)
                        break
    # 类型金标准从 CDN 实时刷新（新皮肤的 L2D/Spine 类型自动正确）
    (MD / "live2d_list.txt").write_text("\n".join(sorted(live2d)), encoding="utf-8")
    (MD / "spinepainting_list.txt").write_text("\n".join(sorted(spine)), encoding="utf-8")
    print(f"类型清单已刷新：live2d {len(live2d)}，spine {len(spine)}")
    return out


def is_skin(name: str) -> bool:
    low = name.lower()
    if not low or low.startswith(("npc", "boss")):
        return False
    if any(m in low for m in VARIANT_MARKERS):
        return False
    if low.endswith(VARIANT_END):
        return False
    return True


def next_skin_id(data: dict) -> int:
    ids = [int(k) for k in data if str(k).isdigit()]
    return (max(ids) + 1) if ids else 100000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写入并重建元数据（默认只预览）")
    ap.add_argument("--ship", default="", help="只处理指定舰船")
    args = ap.parse_args()

    skins = json.loads((MD / "skins.json").read_text(encoding="utf-8"))
    local_paintings = {s["painting"] for s in skins}
    local_paintings_low = {p.lower() for p in local_paintings}
    # 基础 painting：每艘船 bundle=="" 的 painting（同一 painting 只认第一个船名，
    # 避免“马可波罗 王座”这类重复基础码导致新皮肤归属歧义）
    base_by_ship: dict[str, str] = {}
    seen_base: set[str] = set()
    for s in skins:
        if s.get("bundle") == "":
            p = s.get("painting", "")
            if p.lower() in seen_base:
                continue
            seen_base.add(p.lower())
            base_by_ship.setdefault(s["ship"], s["painting"])

    print("正在抓取 CDN 清单…")
    all_names = cdn_paintings()
    candidates = sorted(
        p for p in all_names
        if is_skin(p) and p not in local_paintings and p.lower() not in local_paintings_low
    )
    print(f"CDN 资源 {len(all_names)}，候选新皮肤 {len(candidates)}")

    # 归属：前缀匹配基础 painting（不区分大小写），剩余部分须为 _数字
    new_by_ship: dict[str, list[str]] = {}
    unattributed: list[str] = []
    for p in candidates:
        if args.ship:
            base = base_by_ship.get(args.ship, "")
            hits = [args.ship] if base and p.lower().startswith(base.lower()) else []
        else:
            hits = [
                ship for ship, base in base_by_ship.items()
                if base and p.lower().startswith(base.lower())
            ]
        # 常规皮肤后缀 _数字；誓约皮肤后缀 _h（如 tianlangxing_h = Alba Sirius）
        hits = [h for h in hits if re.fullmatch(r"_\d+|_h", p[len(base_by_ship[h]):])]
        if len(hits) == 1:
            new_by_ship.setdefault(hits[0], []).append(p)
        else:
            unattributed.append(p)

    # 抓 bwiki 皮肤名并配对
    added: list[dict] = []
    review: list[dict] = []
    for ship in sorted(new_by_ship):
        if args.ship and ship != args.ship:
            continue
        names = sorted(new_by_ship[ship])
        try:
            wiki_names = wiki_skin_names(ship)
        except Exception as e:  # noqa: BLE001
            review.append({"ship": ship, "paintings": names, "reason": f"bwiki 抓取失败: {e}"})
            continue
        existing = {s["name"] for s in skins if s["ship"] == ship}
        existing_norm = {norm_name(n) for n in existing}
        fresh_names = [n for n in wiki_names if norm_name(n) not in existing_norm]
        if len(fresh_names) == len(names):
            for painting, name in zip(names, fresh_names):
                added.append({"ship": ship, "name": name, "painting": painting})
        else:
            review.append({
                "ship": ship,
                "paintings": names,
                "bwiki_new_names": fresh_names,
                "reason": f"数量不匹配（CDN {len(names)} vs bwiki 新增 {len(fresh_names)}）",
            })

    print(f"\n自动匹配 {len(added)} 个新皮肤：")
    for a in added:
        print(f"  + {a['ship']}｜{a['name']}｜{a['painting']}")
    print(f"\n待人工确认 {len(review)} 项：")
    for r in review:
        print("  ?", r)
    if unattributed:
        print(f"\n无法归属 {len(unattributed)} 个候选：")
        for p in unattributed[:20]:
            print("  ?", p)

    report = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "added": added,
        "review": review,
        "unattributed": unattributed,
    }
    (MD / "update_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    if not args.apply:
        print("\n[dry-run] 未写入。加 --apply 实际更新。")
        return 0
    if not added:
        print("\n没有可自动写入的新皮肤。")
        return 0

    data = json.loads(OFF_SKIN.read_text(encoding="utf-8"))
    skin_id = next_skin_id(data)
    for a in added:
        key = str(skin_id)
        skin_id += 1
        if key in data:
            continue
        base = base_by_ship.get(a["ship"], "")
        # 找 ship_group：本地 skins.json 没有 group，从官方表反查 painting
        group = None
        for v in data.values():
            if v.get("painting") == base:
                group = v.get("ship_group")
                break
        if group is None:
            review.append({
                "ship": a["ship"], "paintings": [a["painting"]],
                "reason": "无法确定 ship_group，跳过写入",
            })
            continue
        data[key] = {
            "id": int(key),
            "ship_group": group,
            "painting": a["painting"],
            "name": a["name"],
            "group_index": 8 if a["painting"].endswith("_h") else (
                int(a["painting"].rsplit("_", 1)[-1]) if re.fullmatch(r".*_\d+", a["painting"]) else 0
            ),
            "skin_type": 4 if a["painting"].lower() in {
                l.strip() for l in (MD / "live2d_list.txt").read_text(encoding="utf-8-sig").splitlines()
            } else 0,
            "prefab": a["painting"],
        }
    OFF_SKIN.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {len(added)} 条到 {OFF_SKIN.name}，重建元数据…")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_build_official_metadata", str(ROOT / "tools" / "build_official_metadata.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.main()
    if rc:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
