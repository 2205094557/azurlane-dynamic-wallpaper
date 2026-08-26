# -*- coding: utf-8 -*-
"""精确重写 merge_extra_ships 函数（只替换该函数，保留中间其它函数）。"""
import re, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
p = r'D:\codex\azurlane-dynamic-wallpaper\tools\sync_wiki_catalog.py'
src = open(p, encoding='utf-8').read()

# 定位 merge_extra_ships 函数：从它的 def 行到下一个顶层 def（行首 def）
m_start = re.search(r'^def merge_extra_ships\(', src, re.M)
assert m_start, '未找到 merge_extra_ships'
start = m_start.start()
# 找下一个顶行 def
rest = src[start:]
m_next = re.search(r'^def ', rest, re.M | re.S)
m_next = re.search(r'(?m)^def ', rest)
for mm in re.finditer(r'(?m)^def ', rest):
    pos = mm.start()
    if pos > 0:
        next_def = start + pos
        break
else:
    next_def = len(src)
old = src[start:next_def]

new_fn = '''def merge_extra_ships(ships: list[dict], skins: list[dict], extras: list[dict], wmap: dict | None = None) -> tuple[list[dict], list[dict]]:
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


'''
src = src[:start] + new_fn + src[next_def:]
open(p, 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
print('merge_extra_ships 精确重写完成，语法 OK')