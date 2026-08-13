"""整合官方数据 → ships.json + skins.json（全量、命名一致、带 Spine/Live2D 类型）。

数据源：
- official/ship_skin_template.json   官方皮肤表
- official/ship_data_statistics.json 官方舰船数据
- official/spinepainting_list.txt / live2d_list.txt  游戏目录（类型金标准）
- ships.json.bwiki                   旧 bwiki 舰船表（用于代码→中文标签交叉对照）
"""
import json
import re
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
OFF = MD / "official"

NAT_FALLBACK = {
    1: "白鹰", 2: "皇家", 3: "重樱", 4: "铁血", 5: "东煌", 6: "撒丁帝国",
    7: "北方联合", 8: "自由鸢尾", 9: "维希教廷", 10: "META", 96: "塞壬",
    97: "飓风", 98: "其他", 99: "？？",
}
RARITY_FALLBACK = {1: "普通", 2: "稀有", 3: "精锐", 4: "超稀有", 5: "海上传奇"}
TYPE_FALLBACK = {
    1: "驱逐", 2: "轻巡", 3: "重巡", 4: "战列", 5: "战巡", 6: "轻航",
    7: "航母", 8: "航战", 9: "重炮", 10: "维修", 11: "潜母", 12: "潜艇", 13: "风帆",
}


def load_list(name):
    for base in (OFF, MD):
        p = base / name
        if p.exists():
            return {line.strip() for line in p.read_text(encoding="utf-8-sig").splitlines() if line.strip()}
    return set()


def clean_name(name):
    name = (name or "").strip()
    if not name or name.startswith("{namecode") or name in ("unknown_undefined", "unknown"):
        return ""
    if re.fullmatch(r"\d+", name) and len(name) <= 3:
        return ""
    return name


def main():
    skins_raw = json.loads((OFF / "ship_skin_template.json").read_text(encoding="utf-8"))
    stat = json.loads((OFF / "ship_data_statistics.json").read_text(encoding="utf-8"))
    spine = load_list("spinepainting_list.txt")
    live2d = load_list("live2d_list.txt")

    # bwiki 舰船表（用于代码→中文标签交叉对照）
    bwiki_path = MD / "bwiki_ships.json"
    bwiki = json.loads(bwiki_path.read_text(encoding="utf-8")) if bwiki_path.exists() else []
    bwiki_by_name = {s.get("name"): s for s in bwiki}

    # 由 stat 交叉对照推导标签
    rarity_map, nat_map, type_map = {}, {}, {}
    for v in stat.values():
        bs = bwiki_by_name.get(v.get("name"))
        if not bs:
            continue
        rarity_map.setdefault(v.get("rarity"), bs.get("rarity", ""))
        nat_map.setdefault(v.get("nationality"), bs.get("faction", ""))
        type_map.setdefault(v.get("type"), bs.get("hull", ""))

    # ship_group -> 基础皮肤名（= 舰船名，含全部新船）
    def base_painting(gs):
        cands = [v for v in gs if not re.search(r"_\d+$", v.get("painting", ""))]
        cands.sort(key=lambda v: len(v.get("painting", "")))
        return cands[0] if cands else gs[0]

    by_group: dict[str, list] = {}
    for v in skins_raw.values():
        by_group.setdefault(str(v.get("ship_group")), []).append(v)

    def stat_name(gid: str) -> str:
        """优先从官方 stat 表解析舰船中文名（解决 {namecode:xxx} 占位符）。"""
        if not str(gid).isdigit():
            return ""
        base = int(gid) * 10
        for suffix in range(10):
            e = stat.get(str(base + suffix))
            if e:
                n = clean_name(e.get("name"))
                if n:
                    return n
        return ""

    ship_by_group: dict[str, dict] = {}
    for gid, gs in by_group.items():
        if not str(gid).isdigit():
            continue
        name = stat_name(gid) or clean_name(base_painting(gs).get("name"))
        if not name:
            continue
        bs = bwiki_by_name.get(name) or {}
        # 尝试从 stat 补英文名
        stat_entry = stat.get(str(int(gid) * 10)) or stat.get(str(gid)) or {}
        ship_by_group[gid] = {
            "name": name,
            "en": bs.get("en") or stat_entry.get("english_name", ""),
            "faction": bs.get("faction", ""),
            "rarity": bs.get("rarity", ""),
            "hull": bs.get("hull", ""),
            "no": str(gid),
        }

    # ships.json（官方命名，按名去重，前后一致）
    seen = set()
    ships = []
    for s in sorted(ship_by_group.values(), key=lambda x: x["name"]):
        if s["name"] in seen:
            continue
        seen.add(s["name"])
        ships.append(s)
    (MD / "ships.json").write_text(json.dumps(ships, ensure_ascii=False, indent=1), encoding="utf-8")

    # skins.json
    def skin_type(painting):
        if painting in live2d:
            return "live2d"
        if painting in spine:
            return "spine"
        return "static"

    out = []
    seen_paintings: set[tuple[str, str]] = set()
    for gid, gs in by_group.items():
        ship = ship_by_group.get(gid)
        if not ship:
            continue
        base = base_painting(gs).get("painting", "")
        for v in gs:
            # CDN 资源名统一小写，官方表里有 U47_2 之类大写名，必须归一化否则下载匹配不到
            painting = v.get("painting", "").lower()
            if painting.startswith("npc"):
                continue
            # 官方表存在同 painting 多行（同一皮肤多 ID / 多 ship_group），只保留第一条
            key = (ship["name"], painting)
            if key in seen_paintings:
                continue
            seen_paintings.add(key)
            # 部分 painting 大小写与基础名不一致（如 Mingshi_2 vs mingshi），不区分大小写判断
            bundle = painting[len(base):] if painting.lower().startswith(base.lower()) else ""
            raw_name = v.get("name", "")
            out.append({
                "ship": ship["name"],
                "name": raw_name if clean_name(raw_name) else ship["name"],
                "bundle": bundle,
                "painting": painting,
                "type": skin_type(painting),
            })

    out.sort(key=lambda x: (x["ship"], x["bundle"]))
    (MD / "skins.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    types = {}
    for s in out:
        types[s["type"]] = types.get(s["type"], 0) + 1
    print("ships:", len(ships), "skins:", len(out), "->", types)
    for s in out:
        if s["ship"] in ("阿尔萨斯", "奇尔沙治", "信浓"):
            print(" ", s["ship"], "|", s["bundle"], "|", s["name"], "|", s["type"])


if __name__ == "__main__":
    main()
