# -*- coding: utf-8 -*-
"""从 B 站碧蓝航线 wiki 图鉴同步角色/皮肤中文名，重建 ships.json / skins.json。

数据源（用户指定的两个图鉴页）：
- 舰船图鉴  https://wiki.biligame.com/blhx/舰船图鉴
    SMW ask 查询：分类 舰娘/联动舰娘/META舰娘/方案舰娘 + 改造
- 换装图鉴  https://wiki.biligame.com/blhx/换装图鉴
    wikitext 中 {{换装图鉴列表|角色|舰种|阵营|皮肤名|换装N|主题|...}} 行

职责：
1. 抓取图鉴 → 写入 resources/metadata/wiki_catalog.json（可离线复用）
2. 以 wiki 图鉴为准修正 ships.json 的船名（乱码/未识别中文名/重复名）
3. 按“换装N”顺序把皮肤中文名对齐到 painting 后缀，覆盖脏名字（含 ?）
4. 报告图鉴里有但本地还没有资源的船（等 CDN 增量更新后自动补齐）

用法：
  python tools/sync_wiki_catalog.py               # 联网抓取并写入
  python tools/sync_wiki_catalog.py --offline     # 仅用本地 wiki_catalog.json
  python tools/sync_wiki_catalog.py --dry-run     # 只打印报告，不写文件
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

try:
    from pypinyin import lazy_pinyin, Style, pinyin
except Exception:  # noqa: BLE001
    lazy_pinyin = None
    pinyin = None
    Style = None

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "resources" / "metadata"
OFF = MD / "official"

WIKI_API = "https://wiki.biligame.com/blhx/api.php"
WIKI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

CATALOG = MD / "wiki_catalog.json"
REPORT = MD / "wiki_sync_report.json"
UPDATE_REPORT = MD / "update_report.json"
EXTRA_SHIPS = MD / "wiki_extra_ships.json"

# 非独立皮肤的绘画码后缀/标记（变体、特效、敌人资源等）
VARIANT_SUFFIXES = (
    "_wjz", "_ex", "_dark", "_alter", "_npc", "_memory", "_hei", "_idolns",
    "_asmr", "_shophx", "_blueprint", "_younv", "_rank", "_res", "_tex",
    "_rw", "_bj", "_n_", "_hx", "_dark_shadow", "_shadow", "_s", "_g", "_h",
)

# 异体字/常见别名统一，用于匹配键
CHAR_ALIASES = {"倶": "俱", "・": "·", "Ⅱ": "II", "Ⅱ": "II"}


def norm(name: str) -> str:
    """生成宽松匹配键：NFKC + 去空白/分隔符 + 异体字统一。"""
    s = unicodedata.normalize("NFKC", name or "")
    s = s.lower()
    for a, b in CHAR_ALIASES.items():
        s = s.replace(a, b)
    s = re.sub(r"[\s\-·・‐‑‒—―−()（）/\\~～★☆?!？！]", "", s)
    return s


def strip_markup(s: str) -> str:
    """去除 wikitext 标记：<ref>…</ref>、[[目标|显示名]]、{{…}}。"""
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s or "", flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    return s.strip()


def wiki_api(params: dict, timeout: int = 60) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=WIKI_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 1.5)
    return {}


def fetch_wiki_catalog() -> dict:
    """抓取两个图鉴页，返回结构化原始数据。"""
    # 舰船图鉴：第一段 ask（舰娘/联动/META/方案）
    q1 = "[[分类:舰娘||联动舰娘||META舰娘||方案舰娘]]"
    d1 = wiki_api({"action": "ask", "query": q1 + "|?稀有度|?类型|?阵营|?编号|limit=1000"})
    ships = d1.get("query", {}).get("results", {})
    # 第二段 ask（改造）
    q2 = "[[分类:改造]]"
    d2 = wiki_api({"action": "ask", "query": q2 + "|?改造后稀有度|?改造后类型|?阵营|?编号|limit=1000"})
    retrofit = d2.get("query", {}).get("results", {})
    # 换装图鉴 wikitext
    d3 = wiki_api({"action": "parse", "page": "换装图鉴", "prop": "wikitext"})
    wt = d3.get("parse", {}).get("wikitext", "")
    rows = []
    for m in re.finditer(r"\{\{换装图鉴列表\|([^}]+)\}\}", wt):
        fields = [strip_markup(f).strip() for f in m.group(1).split("|")]
        if len(fields) >= 5 and fields[3]:
            rows.append(fields)
    return {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "ships": ships,
        "retrofit": retrofit,
        "skins": rows,
    }


def build_wiki_ships(raw: dict) -> dict:
    """把原始图鉴整理为 wiki 船表：norm_key -> 船信息（含皮肤名列表）。"""
    ships: dict[str, dict] = {}

    def add(name, hull="", faction="", rarity="", no="", kind="ask"):
        key = norm(name)
        if not key:
            return
        ent = ships.setdefault(
            key,
            {"name": name, "aliases": [], "hull": "", "faction": "", "rarity": "", "no": "", "skins": []},
        )
        if name not in ent["aliases"]:
            ent["aliases"].append(name)
        if hull and not ent["hull"]:
            ent["hull"] = hull
        if faction and not ent["faction"]:
            ent["faction"] = faction
        if rarity and not ent["rarity"]:
            ent["rarity"] = rarity
        if no and not ent["no"]:
            ent["no"] = no

    for title, po in raw.get("ships", {}).items():
        p = po.get("printouts", {})
        add(
            title,
            rarity=(p.get("稀有度") or [""])[0],
            hull=(p.get("类型") or [""])[0],
            faction=(p.get("阵营") or [""])[0],
            no=(p.get("编号") or [""])[0],
        )
    for title, po in raw.get("retrofit", {}).items():
        p = po.get("printouts", {})
        key = norm(title)
        ent = ships.get(key)
        if ent:
            # 改造页与基础船同名：只补缺失字段
            ent["rarity"] = ent["rarity"] or (p.get("改造后稀有度") or [""])[0]
            ent["hull"] = ent["hull"] or (p.get("改造后类型") or [""])[0]
            ent["faction"] = ent["faction"] or (p.get("阵营") or [""])[0]
            ent["no"] = ent["no"] or (p.get("编号") or [""])[0]
        else:
            add(
                title,
                rarity=(p.get("改造后稀有度") or [""])[0],
                hull=(p.get("改造后类型") or [""])[0],
                faction=(p.get("阵营") or [""])[0],
                no=(p.get("编号") or [""])[0],
            )

    for r in raw.get("skins", []):
        if len(r) < 5:
            continue
        ship, hull, faction, skin_name, order = r[0], r[1], r[2], r[3], r[4]
        key = norm(ship)
        ent = ships.setdefault(
            key,
            {"name": ship, "aliases": [ship], "hull": "", "faction": "", "rarity": "", "no": "", "skins": []},
        )
        ent["skins"].append({"name": skin_name, "order": order, "theme": r[5] if len(r) >= 6 else ""})
        if hull and not ent["hull"]:
            ent["hull"] = hull
        if faction and not ent["faction"]:
            ent["faction"] = faction
    return ships


def clean_name(name: str) -> str:
    name = strip_markup(name or "").strip()
    if not name or name.startswith("{namecode") or name in ("unknown_undefined", "unknown"):
        return ""
    if re.fullmatch(r"\d+", name) and len(name) <= 3:
        return ""
    return name


def skin_type(painting: str) -> str:
    if painting in _LIVE2D:
        return "live2d"
    if painting in _SPINE:
        return "spine"
    return "static"


_SPINE = {line.strip() for line in (MD / "spinepainting_list.txt").read_text(encoding="utf-8-sig").splitlines() if line.strip()}
_LIVE2D = {line.strip() for line in (MD / "live2d_list.txt").read_text(encoding="utf-8-sig").splitlines() if line.strip()}


def painting_pinyin(name: str) -> str:
    """中文名 → 拼音字符串（小写、仅保留字母数字，取常用读音）。"""
    if lazy_pinyin is None:
        return ""
    parts = lazy_pinyin(name or "", errors="ignore")
    return "".join(re.sub(r"[^a-z0-9]", "", p.lower()) for p in parts)


def painting_pinyin_variants(name: str) -> list[str]:
    """中文名 → 全部可能读音组合（处理“什”“乐”等多音字），组合数过大时只取常用读音。"""
    if pinyin is None or Style is None:
        return [painting_pinyin(name)]
    parts = pinyin(name or "", style=Style.NORMAL, heteronym=True, errors="ignore")
    combos: list[str] = [""]
    for readings in parts:
        readings = [re.sub(r"[^a-z0-9]", "", r.lower()) for r in readings]
        readings = [r for r in readings if r]
        if not readings:
            continue
        if len(combos) * len(readings) > 64:
            combos = [c + readings[0] for c in combos]
        else:
            combos = [c + r for c in combos for r in readings]
    return combos


def is_new_ship_base(p: str) -> bool:
    """判断 CDN 无法归属的绘画码是否可能是新船的基础立绘（而非变体/敌人资源）。"""
    low = p.lower()
    if not low or len(low) < 2:
        return False
    if low.startswith(("npc", "boss", "unknown")) or low in ("mat", "emperor"):
        return False
    if re.search(r"_\d+$", low):
        return False
    if any(m in low for m in VARIANT_SUFFIXES):
        return False
    return True


def find_wiki_ship_for_painting(base: str, wmap: dict, unmatched: set[str]) -> dict | None:
    """按 代码直配 → 拼音精确 → 拼音前缀 在“尚无本地资源的图鉴船”里找对应船。"""
    b = base.lower()
    # 1) 代码直配（2b→2B、u2501→U-2501、z14→Z14、22、33、a2…）
    for key in unmatched:
        if norm(wmap[key]["name"]) == norm(b):
            return wmap[key]
    # 2) 拼音精确（gelifen→格里芬、sali→萨里…）
    exact = []
    for key in unmatched:
        w = wmap[key]
        if b in painting_pinyin_variants(w["name"]):
            exact.append(w)
    if len(exact) == 1:
        return exact[0]
    # 3) 拼音前缀（makesi→马克斯·殷麦曼、molici→莫里茨亲王、gezi→葛兹·冯·伯利欣根）
    pref = []
    for key in unmatched:
        w = wmap[key]
        variants = painting_pinyin_variants(w["name"])
        if len(b) >= 4 and any(py.startswith(b) and len(py) > len(b) for py in variants):
            pref.append(w)
    if len(pref) == 1:
        return pref[0]
    if len(pref) > 1:
        pref.sort(key=lambda w: len(w["name"]))
        return pref[0]
    return None


def find_meta_ship(core: str, wmap: dict, unmatched: set[str]) -> dict | None:
    """X_alter → Y·META：核心拼音 X 匹配 META 船名去掉“·META”后的部分。"""
    cands = []
    for key in unmatched:
        w = wmap[key]
        name = w["name"]
        nm = norm(name)
        if not nm.endswith("meta"):
            continue
        base_cn = re.sub(r"[·\s]?META$", "", name, flags=re.I)
        variants = painting_pinyin_variants(base_cn)
        if core in variants or any(v.startswith(core) and len(core) >= 4 and len(v) > len(core) for v in variants):
            cands.append(w)
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        cands.sort(key=lambda w: len(w["name"]))
        return cands[0]
    return None


def attribute_new_ships(
    unattributed: list[str],
    wmap: dict,
    assigned: dict[str, str],
    existing_paintings: set[str],
) -> tuple[list[dict], list[dict], list[dict]]:
    """把 CDN 无法归属的绘画码匹配到图鉴新船，返回 (ships, skins, report)。"""
    base_set: set[str] = set()
    for p in unattributed:
        p = p.strip().lower()
        if is_new_ship_base(p):
            base_set.add(p)

    # 前缀归组：base + base_N
    by_prefix: dict[str, list[str]] = {}
    for p in unattributed:
        p = p.strip().lower()
        for b in base_set:
            if p == b or p.startswith(b + "_"):
                by_prefix.setdefault(b, []).append(p)
    for b in by_prefix:
        by_prefix[b] = sorted(set(by_prefix[b]))

    matched_keys = set(assigned.values())
    unmatched = {k for k in wmap if k not in matched_keys}
    new_ships: list[dict] = []
    new_skins: list[dict] = []
    report: list[dict] = []

    for base in sorted(by_prefix):
        paints = by_prefix[base]
        if any(p in existing_paintings for p in paints):
            continue
        w = find_wiki_ship_for_painting(base, wmap, unmatched)
        if not w:
            continue
        rows = w["skins"]
        if rows and len(paints) != len(rows) + 1:
            continue  # 数量对不上，避免错配
        outfit_paints = [p for p in paints if p != base]
        if rows and len(outfit_paints) != len(rows):
            continue
        # 通过校验：写入新船 + 皮肤
        name = w["name"]
        no = "WIKI-" + norm(name)
        new_ships.append({
            "name": name, "en": "", "faction": w.get("faction", ""),
            "rarity": w.get("rarity", ""), "hull": w.get("hull", ""), "no": no,
        })
        for p in paints:
            idx = outfit_paints.index(p) if p in outfit_paints else -1
            if idx >= 0 and idx < len(rows):
                sname = rows[idx]["name"]
            else:
                sname = name
            bundle = p[len(base):]
            new_skins.append({
                "ship": name, "name": sname, "bundle": bundle,
                "painting": p, "type": skin_type(p),
            })
        report.append({"name": name, "paintings": paints, "skins": len(rows)})
        unmatched.discard(next((k for k in unmatched if wmap[k] is w), ""))

    # META 船：X_alter → Y·META（与模板中既有 META 船的 _alter 命名约定一致）
    meta_prefix: dict[str, list[str]] = {}
    for p in unattributed:
        low = p.strip().lower()
        if low.endswith("_alter"):
            meta_prefix.setdefault(low, []).append(low)
    for low in list(meta_prefix):
        for p in unattributed:
            pl = p.strip().lower()
            if pl != low and pl.startswith(low + "_") and pl not in meta_prefix.get(low, []):
                meta_prefix[low].append(pl)
        meta_prefix[low] = sorted(set(meta_prefix[low]))

    for base in sorted(meta_prefix):
        paints = meta_prefix[base]
        if any(p in existing_paintings for p in paints):
            continue
        core = base[:-6]
        w = find_meta_ship(core, wmap, unmatched)
        if not w:
            continue
        rows = w["skins"]
        if rows and len(paints) != len(rows) + 1:
            continue
        name = w["name"]
        new_ships.append({
            "name": name, "en": "", "faction": w.get("faction", ""),
            "rarity": w.get("rarity", ""), "hull": w.get("hull", ""), "no": "WIKI-" + norm(name),
        })
        for p in paints:
            idx = paints.index(p) - 1 if p != base else -1
            sname = rows[idx]["name"] if idx >= 0 and idx < len(rows) else name
            new_skins.append({
                "ship": name, "name": sname, "bundle": p[len(base):],
                "painting": p, "type": skin_type(p),
            })
        report.append({"name": name, "paintings": paints, "skins": len(rows)})
        unmatched.discard(next((k for k in unmatched if wmap[k] is w), ""))
    return new_ships, new_skins, report


def load_extra_ships() -> list[dict]:
    if not EXTRA_SHIPS.exists():
        return []
    try:
        return json.loads(EXTRA_SHIPS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def merge_extra_ships(ships: list[dict], skins: list[dict], extras: list[dict]) -> tuple[list[dict], list[dict]]:
    """把持久化的图鉴新船合并进输出（模板里已有同名同资源的跳过）。"""
    out_names = {s["name"] for s in ships}
    out_paints = {s.get("painting", "") for s in skins}
    add_ships: list[dict] = []
    add_skins: list[dict] = []
    for e in extras:
        missing_skins = [s for s in e.get("skins", []) if s.get("painting") not in out_paints]
        if not missing_skins and e.get("name") in out_names:
            continue
        add_ships.append({
            "name": e.get("name", ""), "en": e.get("en", ""),
            "faction": e.get("faction", ""), "rarity": e.get("rarity", ""),
            "hull": e.get("hull", ""), "no": e.get("no", ""),
        })
        add_skins.extend(missing_skins)
    for sk in add_skins:
        sk["type"] = skin_type(sk.get("painting", ""))
    return add_ships, add_skins


def read_unattributed() -> list[str]:
    if not UPDATE_REPORT.exists():
        return []
    try:
        ur = json.loads(UPDATE_REPORT.read_text(encoding="utf-8"))
        return ur.get("unattributed", []) or []
    except Exception:  # noqa: BLE001
        return []


def load_groups() -> list[dict]:
    """从官方皮肤表 + 数据统计表构建舰船分组。"""
    skins_raw = json.loads((OFF / "ship_skin_template.json").read_text(encoding="utf-8"))
    stat = json.loads((OFF / "ship_data_statistics.json").read_text(encoding="utf-8"))

    by_group: dict[str, list[dict]] = {}
    for v in skins_raw.values():
        by_group.setdefault(str(v.get("ship_group")), []).append(v)

    def stat_name(gid: str, base_tpl_name: str) -> str:
        # 1) 常规键 gid*10+suffix（如 307081）
        base = int(gid) * 10
        for suffix in range(10):
            e = stat.get(str(base + suffix))
            if e:
                n = clean_name(e.get("name"))
                if n:
                    return n
        # 2) 模板基础皮肤名（与旧构建一致）
        return clean_name(base_tpl_name)

    def base_painting(gs):
        cands = [v for v in gs if not re.search(r"_\d+$", v.get("painting", ""))]
        cands.sort(key=lambda v: len(v.get("painting", "")))
        return cands[0] if cands else gs[0]

    groups = []
    for gid, gs in by_group.items():
        base = base_painting(gs)
        gs_sorted = sorted(gs, key=lambda v: int(v.get("group_index", 0)))
        base_tpl_name = base.get("name", "")
        outfits = []
        for v in gs_sorted:
            gi = int(v.get("group_index", 0))
            painting = v.get("painting", "").lower()
            is_retrofit = painting.endswith("_g") or str(v.get("name", "")).endswith(".改")
            if gi >= 1 and not is_retrofit:
                outfits.append({"painting": painting, "gi": gi, "name": clean_name(v.get("name")) or ""})
        groups.append({
            "gid": gid,
            "stat_name": stat_name(gid, base_tpl_name),
            "base_painting": base.get("painting", "").lower(),
            "skins": gs_sorted,
            "outfits": outfits,
        })
    return groups


def match_groups(groups: list[dict], wmap: dict) -> dict[str, str]:
    """gid -> wiki norm key。先按船名精确匹配，再按皮肤名重叠匹配。"""
    w_skin_norms = {key: {norm(s["name"]) for s in w["skins"]} for key, w in wmap.items()}
    candidates: list[tuple[int, str, str, str]] = []  # (score, gid, wiki_key, reason)
    for g in groups:
        gkey = norm(g["stat_name"])
        if gkey and gkey in wmap:
            w = wmap[gkey]
            ov = sum(1 for o in g["outfits"] if norm(o["name"]) in w_skin_norms[gkey])
            candidates.append((1000 + ov * 10, g["gid"], gkey, "船名"))
        g_out_norm = {norm(o["name"]) for o in g["outfits"] if o["name"]}
        if not g_out_norm:
            continue
        for key, w in wmap.items():
            if not w["skins"]:
                continue
            ov = len(g_out_norm & w_skin_norms[key])
            if ov:
                candidates.append((ov * 10, g["gid"], key, "皮肤名"))

    assigned: dict[str, str] = {}
    taken: set[str] = set()
    for score, gid, key, reason in sorted(candidates, key=lambda x: (-x[0], x[1])):
        if gid in assigned or key in taken:
            continue
        assigned[gid] = key
        taken.add(key)
    return assigned


def order_value(label: str) -> int:
    """换装N → N；誓约 → 999（排在最后）。"""
    m = re.fullmatch(r"换装(\d+)", label or "")
    if m:
        return int(m.group(1))
    if label == "换装":
        return 1
    if label == "誓约":
        return 999
    return 500


def skin_name_for(wiki_skins: list[dict], outfits: list[dict], base_name: str) -> dict[str, dict]:
    """painting -> {"name": 皮肤中文名, "theme": 皮肤系列}。

    优先按名字匹配（模板自带的皮肤名通常是正确的，且能修掉 ?/错字/namecode）；
    匹配不上的再按位置对齐：wiki 行分“换装N”与“誓约”两组，本地分“普通皮肤”与
    “_h 誓约”两组，组内按顺序对齐（换装N 按编号、本地按 group_index）。
    """
    by_painting: dict[str, dict] = {}
    used: set[int] = set()
    # 1) 名字匹配（唯一命中才用）
    for o in outfits:
        n = norm(o["name"])
        if not n:
            continue
        hits = [i for i, w in enumerate(wiki_skins) if norm(w["name"]) == n]
        if len(hits) == 1:
            w = wiki_skins[hits[0]]
            by_painting[o["painting"]] = {"name": w["name"], "theme": w.get("theme", "")}
            used.add(hits[0])
    # 2) 剩余按位置对齐
    remain_wiki = [w for i, w in enumerate(wiki_skins) if i not in used]
    remain_outfits = [o for o in outfits if o["painting"] not in by_painting]
    wiki_normal = sorted(
        (w for w in remain_wiki if w["order"] != "誓约"),
        key=lambda w: (order_value(w["order"]), id(w)),
    )
    wiki_oath = [w for w in remain_wiki if w["order"] == "誓约"]
    local_normal = [o for o in remain_outfits if not o["painting"].endswith("_h")]
    local_oath = [o for o in remain_outfits if o["painting"].endswith("_h")]
    if len(wiki_normal) == len(local_normal):
        for o, w in zip(local_normal, wiki_normal):
            by_painting.setdefault(o["painting"], {"name": w["name"], "theme": w.get("theme", "")})
    if len(wiki_oath) == len(local_oath):
        for o, w in zip(local_oath, wiki_oath):
            by_painting.setdefault(o["painting"], {"name": w["name"], "theme": w.get("theme", "")})
    return by_painting


def build_output(groups: list[dict], assigned: dict[str, str], wmap: dict, current_ships: list[dict]) -> tuple[list[dict], list[dict], dict]:
    stat = json.loads((OFF / "ship_data_statistics.json").read_text(encoding="utf-8"))

    cur_by_gid = {s.get("no", ""): s for s in current_ships}
    ships_out: list[dict] = []
    skins_out: list[dict] = []
    report = {"renamed_ships": [], "fixed_skins": [], "missing_wiki": []}
    seen_ships: set[str] = set()
    seen_paintings: set[tuple[str, str]] = set()
    emitted_paints: set[str] = set()
    named_bases = {g.get("base_painting", "").lower() for g in groups if g.get("stat_name")}
    placeholder_groups: list[dict] = []

    for g in groups:
        key = assigned.get(g["gid"])
        w = wmap.get(key) if key else None
        old_name = g["stat_name"]
        if w:
            name = w["name"]
        else:
            name = old_name
        if not name:
            # 9xxxxx 新船分组：本地官方表/namecode 解析不出中文名（如 苏维埃同盟）。
            # 先用基础绘画码（拼音）占位输出，保证能下载；
            # 之后 wiki/官方数据补全时，match_groups 会接管并自动改成真名。
            base_b = g.get("base_painting", "").lower()
            if (
                is_new_ship_base(base_b)
                and "_" not in base_b
                and "-" not in base_b
                and any(ch.isalpha() for ch in base_b)
                and base_b not in named_bases
                and base_b not in emitted_paints
            ):
                name = base_b
                placeholder_groups.append({"gid": g["gid"], "name": base_b})
            else:
                continue

        cur = cur_by_gid.get(g["gid"], {})
        if w:
            faction = w["faction"] or cur.get("faction", "")
            hull = w["hull"] or cur.get("hull", "")
            rarity = w["rarity"] or cur.get("rarity", "")
        else:
            faction, hull, rarity = cur.get("faction", ""), cur.get("hull", ""), cur.get("rarity", "")
        stat_en = ""
        base = int(g["gid"]) * 10
        for suffix in range(10):
            e = stat.get(str(base + suffix))
            if e and e.get("english_name"):
                stat_en = e["english_name"]
                break
        en = cur.get("en") or stat_en or ""

        if name != old_name and old_name:
            report["renamed_ships"].append({"from": old_name, "to": name, "reason": "图鉴" if w else "保留"})

        if name not in seen_ships:
            seen_ships.add(name)
            ships_out.append({
                "name": name, "en": en, "faction": faction, "rarity": rarity,
                "hull": hull, "no": g["gid"],
            })

        names_by_painting = skin_name_for(w["skins"] if w else [], g["outfits"], name)
        for v in g["skins"]:
            painting = v.get("painting", "").lower()
            if painting.startswith("npc"):
                continue
            emitted_paints.add(painting)
            key2 = (name, painting)
            if key2 in seen_paintings:
                continue
            seen_paintings.add(key2)
            gi = int(v.get("group_index", 0))
            is_base = gi == 0
            is_retrofit = painting.endswith("_g") or str(v.get("name", "")).endswith(".改")
            raw = clean_name(v.get("name"))
            if is_base:
                sname = name
                stheme = ""
            elif is_retrofit:
                sname = raw if raw else f"{name}.改"
                stheme = ""
            else:
                info = names_by_painting.get(painting)
                sname = info["name"] if info else (raw if raw else name)
                stheme = info["theme"] if info else ""
            bundle = painting[len(g["base_painting"]):] if painting.lower().startswith(g["base_painting"].lower()) else ""
            if not is_base and not is_retrofit and names_by_painting.get(painting) and raw and raw != names_by_painting[painting]:
                report["fixed_skins"].append({"ship": name, "painting": painting, "from": raw, "to": names_by_painting[painting]})
            skins_out.append({
                "ship": name, "name": sname, "bundle": bundle,
                "painting": painting, "type": skin_type(painting), "theme": stheme,
            })

    # 图鉴有但本地无组的船
    matched_keys = set(assigned.values())
    for key, w in wmap.items():
        if key in matched_keys:
            continue
        report["missing_wiki"].append({
            "name": w["name"], "faction": w["faction"], "hull": w["hull"],
            "skins": len(w["skins"]),
        })

    ships_out.sort(key=lambda x: x["name"])
    skins_out.sort(key=lambda x: (x["ship"], x["bundle"]))
    report["placeholder_groups"] = placeholder_groups
    # 合并“同名多部件”皮肤：游戏里一个皮肤可能拆成多个 Spine 骨架
    #（如 云龙-溶于重重夜色 = yunlong_2 角色 + yunlong_3 背景），合并为一个条目并记录 parts。
    merged_map: dict[tuple[str, str, str], dict] = {}
    for sk in skins_out:
        key = (sk["ship"], sk["name"], sk["type"])
        is_multi = sk["type"] == "spine" and sk["name"] != sk["ship"]
        if is_multi and key in merged_map:
            entry = merged_map[key]
            entry["parts"] = sorted(set(entry.get("parts", [entry["painting"]]) + [sk["painting"]]))
        else:
            new = dict(sk)
            if is_multi:
                new["parts"] = [sk["painting"]]
            merged_map[key] = new
    skins_out = list(merged_map.values())
    return ships_out, skins_out, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="不联网，用本地 wiki_catalog.json")
    ap.add_argument("--dry-run", action="store_true", help="只打印报告不写文件")
    args = ap.parse_args()

    if args.offline:
        if not CATALOG.exists():
            print("未找到本地 wiki_catalog.json，请先联网运行一次")
            return 1
        raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    else:
        try:
            raw = fetch_wiki_catalog()
            CATALOG.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"图鉴已抓取：{raw['fetched_at']}  船 {len(raw['ships'])} + 改造 {len(raw['retrofit'])}，皮肤行 {len(raw['skins'])}")
        except Exception as e:  # noqa: BLE001
            print(f"抓取失败：{e}")
            if CATALOG.exists():
                print("使用本地缓存的 wiki_catalog.json 继续")
                raw = json.loads(CATALOG.read_text(encoding="utf-8"))
            else:
                return 1

    wmap = build_wiki_ships(raw)
    print(f"wiki 船表：{len(wmap)} 艘")
    groups = load_groups()
    assigned = match_groups(groups, wmap)
    print(f"本地分组：{len(groups)}，匹配到图鉴：{len(assigned)}")

    current_ships = json.loads((MD / "ships.json").read_text(encoding="utf-8"))
    ships, skins, report = build_output(groups, assigned, wmap, current_ships)

    template_paints = {s.get("painting", "") for s in skins}
    template_names = {s.get("name") for s in ships}

    # 1) 先合并持久化的图鉴新船（防止被官方表重建抹掉）
    extras = load_extra_ships()
    es, esk = merge_extra_ships(ships, skins, extras)
    ships.extend(es)
    skins.extend(esk)
    report["extra_ships_total"] = len(extras)

    # 2) CDN 无法归属的绘画码 → 新发现的图鉴船（格里芬/萨里/2B 等）
    unattributed = read_unattributed()
    new_ships: list[dict] = []
    new_skins: list[dict] = []
    new_report: list[dict] = []
    if unattributed:
        existing = {s.get("painting", "") for s in skins}
        new_ships, new_skins, new_report = attribute_new_ships(
            unattributed, wmap, assigned, existing,
        )
        ships.extend(new_ships)
        skins.extend(new_skins)
        report["new_ships"] = new_report

    if new_report or es:
        skip = {r["name"] for r in new_report}
        skip |= {e.get("name") for e in extras}
        report["missing_wiki"] = [
            m for m in report["missing_wiki"] if m["name"] not in skip
        ]
        ships.sort(key=lambda x: x["name"])
        skins.sort(key=lambda x: (x["ship"], x["bundle"]))

    # 3) 持久化：已有 extras + 本次新增（按船名去重；已完全并入官方表的剔除）
    extra_by_name = {e.get("name"): e for e in extras}
    new_extra_skins: dict[str, list[dict]] = {}
    for sk in new_skins:
        new_extra_skins.setdefault(sk.get("ship", ""), []).append(sk)
    for r in new_report:
        nm = r.get("name", "")
        ship = next((s for s in new_ships if s.get("name") == nm), None)
        if not ship:
            continue
        extra_by_name[nm] = {
            "name": nm, "en": ship.get("en", ""),
            "faction": ship.get("faction", ""), "rarity": ship.get("rarity", ""),
            "hull": ship.get("hull", ""), "no": ship.get("no", ""),
            "skins": new_extra_skins.get(nm, []),
        }
    pruned = [
        e for e in extra_by_name.values()
        if any(sk.get("painting") not in template_paints for sk in e.get("skins", []))
    ]
    EXTRA_SHIPS.write_text(json.dumps(pruned, ensure_ascii=False, indent=1), encoding="utf-8")

    report.update({
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "wiki_fetched_at": raw.get("fetched_at", ""),
        "ships_total": len(ships),
        "skins_total": len(skins),
        "matched_groups": len(assigned),
        "renamed_ships": report["renamed_ships"],
        "fixed_skins": report["fixed_skins"],
        "missing_wiki": report["missing_wiki"],
    })
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nships: {len(ships)}  skins: {len(skins)}")
    print(f"改船名 {len(report['renamed_ships'])} 处：")
    for r in report["renamed_ships"][:40]:
        print(f"   {r['from']} -> {r['to']}  ({r['reason']})")
    print(f"皮肤名修正 {len(report['fixed_skins'])} 处：")
    for r in report["fixed_skins"][:40]:
        print(f"   {r['ship']}/{r['painting']}: {r['from']} -> {r['to']}")
    print(f"图鉴新船归属 {len(new_report)} 艘：")
    for r in new_report:
        print(f"   + {r['name']} ({r['paintings']})")
    print(f"图鉴有但本地无资源 {len(report['missing_wiki'])} 艘：")
    for m in report["missing_wiki"][:40]:
        print(f"   {m['name']} ({m['faction']}/{m['hull']}, 皮肤 {m['skins']})")

    if args.dry_run:
        print("\n[dry-run] 未写入 ships.json / skins.json")
        return 0
    (MD / "ships.json").write_text(json.dumps(ships, ensure_ascii=False, indent=1), encoding="utf-8")
    (MD / "skins.json").write_text(json.dumps(skins, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n已写入 ships.json / skins.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
