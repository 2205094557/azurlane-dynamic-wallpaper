# -*- coding: utf-8 -*-
"""从 B 站碧蓝航线 wiki 图鉴同步角色/皮肤中文名，重建 ships.json / skins.json。

数据源（用户指定的两个图鉴页）：
- 舰船图鉴  https://wiki.biligame.com/blhx/舰船图鉴
    SMW ask 查询：分类 舰娘/联动舰娘/META舰娘/方案舰娘 + 改造
- 换装图鉴  https://wiki.biligame.com/blhx/换装图鉴
    2026-09 改版后：数据在 [[模块:ClothList/json]]（结构化 JSON 数组，
    字段 船名/舰种/阵营/换装名称/换装/主题/…），页面本体不再内联模板；
    旧版 {{换装图鉴列表|…}} wikitext 模板作为回退保留（见 fetch_clothlist_rows）。
    两种来源统一为行格式 [船名, 舰种, 阵营, 换装名, 换装N, 主题]（下游不变）。

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
SKIN_PATCHES = MD / "skin_name_patches.json"

# 非独立皮肤的绘画码后缀/标记（变体、特效、敌人资源等）
VARIANT_SUFFIXES = (
    "_wjz", "_ex", "_dark", "_alter", "_npc", "_memory", "_hei", "_idolns",
    "_asmr", "_shophx", "_blueprint", "_younv", "_rank", "_res", "_tex",
    "_rw", "_bj", "_n_", "_hx", "_dark_shadow", "_shadow", "_s", "_g", "_h",
)

# 图鉴名 → 无拼音对应关系的 painting 代号（新船代号与中文名脱钩，只能手写映射）。
# 例：伊14 的图鉴名在 wmap 里是"伊14"（别名十诗），painting 代号是 i14。
PAINTING_ALIASES = {
    "i14": "伊14",
    "i14_2": "伊14",
}

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


def fetch_clothlist_rows() -> list[list[str]]:
    """抓取换装总表，返回旧格式行 [船名, 舰种, 阵营, 换装名, 换装N, 主题]。

    2026-09 起 wiki 换装图鉴改版：页面本体不再内联 {{换装图鉴列表|…}} 模板，
    完整数据搬到 [[模块:ClothList/json]]（结构化 JSON 数组，字段：
    船名/舰种/阵营/换装名称/换装/主题/价格/获取方式/表情差分/立绘类型/背景类型/
    背景物件/备注/实装时间，换装形如 "换装" / "换装2" / … / "誓约"）。
    本函数把两种来源统一成下游使用的行格式，互为主备：
      1) 模块:ClothList/json（新版，首选）
      2) {{换装图鉴列表|…}}（旧版 wikitext 模板，wiki 若回退仍可用）
    """
    # ---- 1) 新版：模块:ClothList/json ----
    try:
        d = wiki_api({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": "模块:ClothList/json",
        })
        pages = d.get("query", {}).get("pages", {})
        # wiki_api 走 formatversion=2：pages 是列表；旧版 API 是 {pageid: {...}} 字典
        page_list = pages if isinstance(pages, list) else list(pages.values())
        content = ""
        for pg in page_list:
            revs = (pg or {}).get("revisions") or []
            if revs:
                slots = revs[0].get("slots") or {}
                main = slots.get("main") or {}
                content = main.get("content") or main.get("*") or ""
                break
        if content.strip():
            data = json.loads(content)
            rows: list[list[str]] = []
            for item in data if isinstance(data, list) else []:
                if not isinstance(item, dict):
                    continue
                ship = clean_name(str(item.get("船名", "")))
                skin = strip_markup(str(item.get("换装名称", ""))).strip()
                if not ship or not skin:
                    continue
                rows.append([
                    ship,
                    str(item.get("舰种", "")),
                    str(item.get("阵营", "")),
                    skin,
                    str(item.get("换装", "")),
                    str(item.get("主题", "")),
                ])
            if rows:
                print(f"[wiki] 换装总表（模块:ClothList/json）{len(rows)} 条")
                return rows
    except Exception as e:  # noqa: BLE001
        print(f"[wiki] 新版换装数据源不可用，回退旧模板解析: {type(e).__name__}: {e}")

    # ---- 2) 旧版：页面内联模板 ----
    d3 = wiki_api({"action": "parse", "page": "换装图鉴", "prop": "wikitext"})
    wt = d3.get("parse", {}).get("wikitext", "")
    if isinstance(wt, dict):
        wt = wt.get("*", "")
    rows = []
    for m in re.finditer(r"\{\{换装图鉴列表\|([^}]+)\}\}", wt):
        fields = [strip_markup(f).strip() for f in m.group(1).split("|")]
        if len(fields) >= 5 and fields[3]:
            rows.append(fields)
    if rows:
        print(f"[wiki] 换装总表（旧模板）{len(rows)} 条")
    else:
        print("[wiki] 警告：换装总表两种来源均无数据")
    return rows


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
    # 换装总表（新版模块 JSON 优先，旧 wikitext 模板回退）
    rows = fetch_clothlist_rows()

    # 个人词条【标题N】补录：
    # 换装总表有时落后于个人页（如埃米尔·贝尔汀总表 3 条、个人页 5 条），
    # 缺了会让新皮肤一直显示英文编号。但逐船抓取成本高（每船一次请求），
    # 因此仅在「本机上确实存在未命名皮肤（name == painting）」的船上做：
    # 这类船通常只有个别几艘，且只在出问题时才请求，正常状态零开销。
    rows_by_ship: dict[str, int] = {}
    for r in rows:
        if r:
            rows_by_ship[norm(r[0])] = rows_by_ship.get(norm(r[0]), 0) + 1
    existing_ships_in_skins = set(rows_by_ship)

    unresolved_ships: set[str] = set()
    try:
        cur_skins = json.loads((MD / "skins.json").read_text(encoding="utf-8"))
        for s in cur_skins if isinstance(cur_skins, list) else []:
            nm = str(s.get("name", ""))
            pt = str(s.get("painting", ""))
            if nm and pt and nm == pt:
                unresolved_ships.add(norm(str(s.get("ship", ""))))
    except Exception:  # noqa: BLE001
        pass

    for title in list(ships.keys()):
        key = norm(title)
        # 不在总表 → 新船，需要抓；在总表但有未命名皮肤 → 可能总表落后，也抓
        if key in existing_ships_in_skins and key not in unresolved_ships:
            continue
        try:
            page_data = wiki_api({"action": "parse", "page": title, "prop": "wikitext"}, timeout=15)
            pwt = page_data.get("parse", {}).get("wikitext", {})
            if isinstance(pwt, dict):
                pwt = pwt.get("*", "")
            titles = []
            for mm in re.finditer(r"\|\s*标题\d+\s*=\s*([^\n|]+)", pwt):
                t = strip_markup(mm.group(1)).strip()
                if t and t not in titles:
                    titles.append(t)
            if titles and title in ships and len(titles) > rows_by_ship.get(key, 0):
                ships[title]["outfit_titles"] = titles
        except Exception:  # noqa: BLE001
            pass

    # 个人页比总表更全时，把缺失的换装**合成总表行**（与总表同格式），
    # 这样它会落盘到 wiki_catalog.json，并参与后续的名字对齐（skin_name_for）。
    # 否则个人页拿到的名字只存在于内存的 ships 字段里，新皮肤仍显示英文编号。
    table_rows = list(rows)
    table_names = {norm(r[3]) for r in rows if len(r) >= 4 and r[3]}
    ship_meta = {}
    for r in rows:
        if len(r) >= 3 and r[0]:
            ship_meta.setdefault(norm(r[0]), (r[0], r[1], r[2]))
    added_rows: list[list[str]] = []
    for title, po in ships.items():
        page_titles = po.get("outfit_titles") or []
        if not page_titles:
            continue
        key = norm(title)
        meta = ship_meta.get(key)
        if meta is None:
            # 该船完全不在总表：用 ask 拿到的信息做元数据
            pr = (po.get("printouts") or {})
            meta = (
                title,
                (pr.get("类型") or [""])[0],
                (pr.get("阵营") or [""])[0],
            )
        ship_display, hull_v, faction_v = meta
        n = 0
        for sname in page_titles:
            if not sname or sname.endswith(".改"):
                continue
            if norm(sname) in table_names:
                n += 1
                continue
            n += 1
            order_label = "换装" if n == 1 else f"换装{n}"
            added_rows.append([ship_display, hull_v, faction_v, sname, order_label, ""])
            table_names.add(norm(sname))
    if added_rows:
        table_rows.extend(added_rows)
        print(f"[wiki] 个人页补录换装行 {len(added_rows)} 条（总表 {len(rows)} → {len(table_rows)}）")

    return {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "ships": ships,
        "retrofit": retrofit,
        "skins": table_rows,
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

    # 兜底补充：无论新船还是老船，如果个人词条已有【标题N】但换装大表未收录最新的换装，
    # 自动把缺失的皮肤名追加到该船的 skins 列表（如埃米尔·贝尔汀的「闪耀的“魔法”」）。
    # 注意排除：①改造条目（以 .改 结尾，属改造不属换装，大表本就不列）
    #          ②模板占位文本（如「这里填换装标题」）
    for title, po in raw.get("ships", {}).items():
        key = norm(title)
        ent = ships.get(key)
        if not ent:
            continue
        page_titles = po.get("outfit_titles") or []
        existing_names = {s.get("name") for s in ent.get("skins", [])}
        for sname in page_titles:
            if not sname or sname in existing_names:
                continue
            if sname.endswith(".改") or "填" in sname and "标题" in sname:
                continue  # 改造条目 / 模板占位文本
            if sname.startswith("这里填") or sname in ("待补充", "未知"):
                continue
            # 计算当前是第几个普通换装
            normal_count = sum(1 for s in ent.get("skins", []) if s.get("order") != "誓约")
            order_label = f"换装{normal_count + 1}" if normal_count > 0 else "换装"
            theme = "" if sname == title else ""
            ent["skins"].append({"name": sname, "order": order_label, "theme": theme})
            existing_names.add(sname)
            print(f"   [单页换装增量补录] {title} -> {sname} ({order_label})")
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
    _TOOLS_DIR = Path(__file__).resolve().parent
    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))
    from npc_filter import is_npc_painting  # noqa: E402

    if is_npc_painting(low) or low in ("mat", "emperor"):
        return False
    if re.search(r"_\d+$", low):
        return False
    if any(m in low for m in VARIANT_SUFFIXES):
        return False
    return True


def find_wiki_ship_for_painting(base: str, wmap: dict, unmatched: set[str]) -> dict | None:
    """按 代码直配 → 别名表 → 拼音精确 → 拼音前缀 在“尚无本地资源的图鉴船”里找对应船。"""
    b = base.lower()
    # 0) 别名表直配（painting 代号与图鉴名无拼音对应：伊14=i14 ↔ 图鉴名"十诗"）
    alias_cn = PAINTING_ALIASES.get(b)
    if alias_cn:
        for key in unmatched:
            if wmap[key]["name"] == alias_cn or norm(wmap[key]["name"]) == norm(alias_cn):
                return wmap[key]
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


def merge_extra_ships(ships: list[dict], skins: list[dict], extras: list[dict], wmap: dict | None = None) -> tuple[list[dict], list[dict]]:
    """把持久化的图鉴新船合并进输出（模板里已有同名同资源的跳过）。

    皮肤名刷新：wiki 换装图鉴后来补录了正式皮肤名（如哈里森 halisen_2 的
    “提前开始的追逐赛？”），而 extras 持久化里是占位名（角色本名）。
    对本船（norm 匹配）用 wiki 皮肤名按换装顺序刷新占位皮肤名——
    无论该船已输出还是本次新加入，避免“更新后仍显示角色本名占位”。
    """
    out_names = {s["name"] for s in ships}
    out_paints = {s.get("painting", "") for s in skins}

    # wiki 船 norm_key -> 皮肤名列表（按换装图鉴行顺序）
    wiki_skin_names: dict[str, list[str]] = {}
    if wmap:
        for key, w in wmap.items():
            names = [sk.get("name", "").strip() for sk in w.get("skins", []) if sk.get("name", "").strip()]
            if names:
                wiki_skin_names[key] = names

    def wnames_for(e) -> list[str] | None:
        if not wmap:
            return None
        wk = None
        for k in wmap:
            if norm(wmap[k]["name"]) == norm(e.get("name", "")):
                wk = k
                break
        return wiki_skin_names.get(wk) if wk else None

    # 刷新一个皮肤 dict 的名字：bundle 换装皮肤按 extras 内顺序对齐 wiki 皮肤名
    def refresh(sk: dict, e: dict, wnames: list[str] | None) -> bool:
        if not wnames or not sk.get("bundle"):
            return False
        outfit_sks = [s for s in e.get("skins", []) if s.get("bundle")]
        try:
            idx = outfit_sks.index(sk)
        except ValueError:
            # sk 可能是副本；按 painting 找位置
            idx = next((i for i, s in enumerate(outfit_sks) if s.get("painting") == sk.get("painting")), -1)
        if 0 <= idx < len(wnames) and wnames[idx] and sk.get("name") != wnames[idx]:
            prev = sk.get("name", "")
            sk["name"] = wnames[idx]
            print(f"   [皮肤名刷新] {e.get('name')}/{sk.get('painting')}: {prev} -> {wnames[idx]}")
            return True
        return False

    add_ships: list[dict] = []
    add_skins: list[dict] = []
    for e in extras:
        wnames = wnames_for(e)
        missing_skins = [s for s in e.get("skins", []) if s.get("painting") not in out_paints]
        if not missing_skins and e.get("name") in out_names:
            # 船已在输出：就地刷新输出列表里该船套皮的占位名
            for sk in e.get("skins", []):
                target = next((s for s in skins if s.get("ship") == e.get("name") and s.get("painting") == sk.get("painting")), None)
                if target:
                    refresh(target, e, wnames)
                else:
                    refresh(sk, e, wnames)
            continue
        # 新加入（本次缺失的皮肤/整船）
        add_ships.append({
            "name": e.get("name", ""), "en": e.get("en", ""),
            "faction": e.get("faction", ""), "rarity": e.get("rarity", ""),
            "hull": e.get("hull", ""), "no": e.get("no", ""),
        })
        for sk in missing_skins:
            refresh(sk, e, wnames)  # 先刷新（保留 e.skins 引用以对齐顺序），再复制
            add_skins.append(dict(sk))
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


# 官方皮肤表缓存（判定「官方占位名」用；懒加载一次）
_OFFICIAL_SKIN_CACHE: dict | None = None


def _official_skins() -> dict:
    global _OFFICIAL_SKIN_CACHE
    if _OFFICIAL_SKIN_CACHE is None:
        try:
            _OFFICIAL_SKIN_CACHE = json.loads(
                (OFF / "ship_skin_template.json").read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            _OFFICIAL_SKIN_CACHE = {}
    return _OFFICIAL_SKIN_CACHE


def is_placeholder_skin(painting: str) -> bool:
    """该 painting 在官方表里是否为「占位条目」（新皮肤，官方尚未录入正式数据）。

    判据（对照已正确命名的同类数据得出）：
      - 表中存在该 painting 且 name == painting（未命名，如 'jinluhao_4'）
      - 且 skin_type == 0（非 L2D/改造等类型）
      - 且 change_skin 与 shop_id 均为空（非商店在售、非形态切换入口）

    这类条目通常是「一款新皮肤的一种表现形态」（如 L2D 版 + Spine 版拆成
    painting_3 / painting_4），官方尚未录入正式名，wiki 换装图鉴里它们共用
    同一个皮肤名。注意与真正的「形态切换皮肤」区分：后者 change_skin 有值
    （如四万十 siwanshi_3/_4，change_skin.group=39906），且 name 已是正式名。
    """
    if not painting:
        return False
    key = painting.lower()
    for _k, v in _official_skins().items():
        if not isinstance(v, dict):
            continue
        if str(v.get("painting", "")).lower() != key:
            continue
        name = str(v.get("name", ""))
        if name != painting:
            return False
        if v.get("skin_type") != 0:
            return False
        if v.get("change_skin") or v.get("shop_id"):
            return False
        return True
    return False


def skin_name_for(wiki_skins: list[dict], outfits: list[dict], base_name: str) -> dict[str, dict]:
    """painting -> {"name": 皮肤中文名, "theme": 皮肤系列}。

    优先按名字匹配（模板自带的皮肤名通常是正确的，且能修掉 ?/错字/namecode）；
    匹配不上的再按位置对齐：wiki 行分“换装N”与“誓约”两组，本地分“普通皮肤”与
    “_h 誓约”两组，组内按顺序对齐（换装N 按编号、本地按 group_index）。

    数量不等的处理：一款皮肤可能拆成多个 painting（形态切换，如新皮肤的
    L2D 版 + Spine 版），此时本地条目数会比 wiki 换装数多。把本地多出的相邻
    条目视作“同款形态”合并到前一个 wiki 名字上（而非整体放弃对齐），
    否则会出现“本机缺基础款导致新皮肤一直显示英文编号”的问题。
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
    _align_with_variants(by_painting, local_normal, wiki_normal)
    _align_with_variants(by_painting, local_oath, wiki_oath)
    return by_painting


def _align_with_variants(
    by_painting: dict[str, dict],
    local: list[dict],
    wiki: list[dict],
) -> None:
    """把 local 按顺序对齐到 wiki；数量不等时把「官方占位条目」当作形态变体。

    仅当 local 比 wiki 多、且多出的条目在官方表里是占位名（is_placeholder_skin）
    时才做形态复用：这类条目是一款新皮肤的另一表现形态（如 L2D 版 + Spine 版），
    官方尚未录入正式名，与相邻条目共用同一个 wiki 皮肤名。

    保护规则（_pick）：官方名若以 wiki 名为前缀且更长（带形态后缀，
    如「共坠的渴慕（L2D）」/「共坠的渴慕（动态）」），保留官方名，只从 wiki 补主题——
    否则会用无后缀的 wiki 名覆盖掉有意义的形态标注。

    数量相等时保持原有的严格顺序对齐（wiki 名为准）。
    """
    if not local or not wiki:
        return

    def _pick(o: dict, w: dict) -> dict:
        """名字决策：官方名带形态后缀时保留它，否则采用 wiki 名。"""
        official = (o.get("name") or "").strip()
        wname = w["name"]
        if official and official != wname and official.startswith(wname) and len(official) > len(wname):
            return {"name": official, "theme": w.get("theme", "")}
        return {"name": wname, "theme": w.get("theme", "")}

    if len(local) == len(wiki):
        for o, w in zip(local, wiki):
            by_painting.setdefault(o["painting"], _pick(o, w))
        return
    if len(local) < len(wiki):
        # 本地条目比 wiki 少：不做对齐（可能本机未下载，避免错配）
        return
    # 本地比 wiki 多：逐名分配，官方占位条目吸附到前一个条目（共用同一个皮肤名）
    variant_idx: set[int] = {i for i, o in enumerate(local) if is_placeholder_skin(o["painting"])}
    assigned: list[int] = []  # 每项对应的 wiki 下标；-1 = 复用前一项名字
    wiki_i = 0
    for i, o in enumerate(local):
        if i in variant_idx and assigned and wiki_i > 0:
            assigned.append(-1)  # 官方占位条目：与前一形态共用 wiki 名
            continue
        if wiki_i < len(wiki):
            assigned.append(wiki_i)
            wiki_i += 1
        else:
            # wiki 名额用完但该条目不是官方占位（= 可能是独立皮肤）：
            # 无法安全判定归属，整体放弃对齐，宁缺勿错
            return
    # wiki 名没能全部用上（形态判定未命中，说明多出的并非占位形态）：放弃对齐
    if wiki_i < len(wiki):
        return
    for i, o in enumerate(local):
        wi = assigned[i] if i < len(assigned) else -1
        if wi >= 0:
            by_painting.setdefault(o["painting"], _pick(o, wiki[wi]))
        else:
            # 复用前一个已分配的 wiki 名（同款皮肤的另一形态）
            prev = None
            for j in range(i - 1, -1, -1):
                if assigned[j] >= 0:
                    prev = wiki[assigned[j]]
                    break
            if prev is not None:
                by_painting.setdefault(o["painting"], _pick(o, prev))


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
            # 若有预置的新皮肤补丁（针对 Wiki 换装大表尚未收录的新换装），优先采纳
            if not is_base and not is_retrofit and SKIN_PATCHES.exists():
                try:
                    patches = json.loads(SKIN_PATCHES.read_text(encoding="utf-8"))
                    patch = patches.get(painting)
                    if patch and patch.get("name"):
                        sname = patch["name"]
                        if patch.get("theme"):
                            stheme = patch["theme"]
                except Exception:
                    pass
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
        # 短缓存：图鉴 5 分钟内抓过就直接复用，避免“检查并更新/仅同步图鉴”
        # 连续点击时每次都联网拉两个大页面（换装图鉴 wikitext 有数 MB）
        cached_raw = None
        if CATALOG.exists():
            try:
                cached_raw = json.loads(CATALOG.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                cached_raw = None
        fresh = False
        if cached_raw:
            try:
                ft = cached_raw.get("fetched_at", "")
                if ft:
                    fresh = (datetime.now() - datetime.fromisoformat(ft)).total_seconds() < 300
            except Exception:  # noqa: BLE001
                fresh = False
        if fresh:
            raw = cached_raw
            print(f"图鉴缓存未过期（{raw['fetched_at']}），跳过联网抓取")
        else:
            try:
                raw = fetch_wiki_catalog()
                CATALOG.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"图鉴已抓取：{raw['fetched_at']}  船 {len(raw['ships'])} + 改造 {len(raw['retrofit'])}，皮肤行 {len(raw['skins'])}")
            except Exception as e:  # noqa: BLE001
                print(f"抓取失败：{e}")
                if cached_raw is not None:
                    print("使用本地缓存的 wiki_catalog.json 继续")
                    raw = cached_raw
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
    es, esk = merge_extra_ships(ships, skins, extras, wmap)
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
