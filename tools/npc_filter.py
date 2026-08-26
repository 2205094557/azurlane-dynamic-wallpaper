# -*- coding: utf-8 -*-
"""NPC / 非玩家立绘过滤名单（塞壬、敌方单位、剧情角色、未知条目等）。

被 build_official_metadata / update_metadata / sync_wiki_catalog 共用，
也用于就地清理历史元数据与已下载资源。判定维度：
  1) ship 名精确匹配（官方 ship_group 名，含特殊字符）
  2) ship 名关键词（安全前缀，不会误伤正常船）
  3) painting 前缀（塞壬量产机 / unknown / 剧情角色拼音）

注意：联动可玩角色（DOA/Hololive/海王星/莱莎等）、META 船、未实装船
（利根/加斯科涅/弗兰德尔等）不属于 NPC，不在过滤范围。
"""

from __future__ import annotations

# 1) ship 名精确匹配：塞壬 / 敌方 / 剧情 / 未知条目
NPC_SHIP_NAMES: frozenset[str] = frozenset({
    # 塞壬仲裁者（塔罗牌命名）
    "仲裁者·司特莲库斯·VIII", "仲裁者·天帕岚斯·XIV", "仲裁者·恩普雷斯·III",
    "仲裁者·托瓦·XVI", "仲裁者·拉沃斯·VI", "仲裁者·提尔瑞特·VII",
    "仲裁者·沐恩·XVIII", "仲裁者·赫米忒·IX", "仲裁者·迪贝路·XV", "仲裁者·麦纪莎·I",
    # 塞壬安蒂克丝
    "观察者", "观察者-零", "净化者", "构建者", "清除者",
    # 塞壬 BOSS / 变体
    "544845544F574552", "▅海▊▇洛▅■芬特▇▆▅", "ladyE", "维序者·埃尔·ACE", "阿尔及利亚？",
    # 敌方单位 / 机械
    "审判机·「战车」", "审判机·「魔术师」",
    "战争协议-堡垒", "战争协议-玉轮", "战争协议-镰刃",
    "导驱type20测试机", "导驱type21测试机",
    "超级AI-TC", "泛用型强化武装(工作用)", "金布里机甲",
    "死神之影", "星之兽", "星之兽？",
    # 剧情 NPC
    "D小姐", "M女士", "TB", "领航员-TB",
    "奥斯塔", "安洁", "好人理查德", "柯蕾", "苝", "「银狐」女士", "马可波罗 王座",
    "神子的休憩", "入浴的小恶魔", "数据集：无数的我", "悠悠假日私语时",
    # 未知 / 异常条目
    "？", "？？", "？？？", "？？？?", "？？？？？",
    "FC-1", "FC-31", "J-10", "J-15", "J-20",
    # 宠物系统
    "指挥喵",
})

# 2) ship 名关键词（只在名字包含时才命中，正常船名不会包含这些词）
NPC_SHIP_KEYWORDS: tuple[str, ...] = (
    "仲裁者", "审判机", "战争协议", "导驱type", "指挥喵",
    "死神之影", "星之兽", "超级AI", "泛用型强化武装", "金布里机甲",
    "神子的休憩", "入浴的小恶魔", "数据集：", "悠悠假日私语时",
)

# 3) painting 前缀：塞壬量产机 / unknown 系列 / 剧情角色拼音。
#    注意：只能放「正常船不会撞前缀」的码。kelei（克雷文 keleiwen）、
#    weineituo（维托里奥·维内托的基础码，与剧情角色"苝"共用）会误伤，不放这里，
#    柯蕾/苝 由上面 ship 精确名单过滤。
NPC_PAINTING_PREFIXES: tuple[str, ...] = (
    "npc", "boss", "unknown",           # 既有过滤规则
    "sairen", "sairenboss",             # 塞壬 BOSS
    "lingyangzhe", "tansuozhe", "linghangyuan",  # 领洋者/探索者/领航员（塞壬量产）
    "qingchuzhe", "zhongcaizhe", "ceshizhe",     # 清除者/仲裁者/测试者
    "hierophant", "starbeast", "dosair",         # 塞壬特殊/剧情
    "tbniang", "madamm", "missd", "aosita", "anjie",  # TB/M女士/D小姐/奥斯塔/安洁
    "richard_white", "silverfox",                # 好人理查德/银狐
)

# 联动可玩角色 painting 前缀（明确不是 NPC，防误伤）
_NPC_PREFIX_EXCLUDE: tuple[str, ...] = ()


def is_npc_ship(name: str) -> bool:
    """ship 名是否属于 NPC / 非玩家角色。"""
    if not name:
        return False
    if name in NPC_SHIP_NAMES:
        return True
    for kw in NPC_SHIP_KEYWORDS:
        if kw in name:
            return True
    return False


def is_npc_painting(painting: str) -> bool:
    """painting（CDN 资源名）是否属于 NPC 立绘。"""
    low = (painting or "").lower()
    if not low:
        return False
    for p in NPC_PAINTING_PREFIXES:
        if low.startswith(p):
            return True
    return False


def is_npc_skin(skin: dict) -> bool:
    """皮肤条目是否属于 NPC：ship 名命中或 painting 命中。"""
    if is_npc_ship(skin.get("ship", "")):
        return True
    for part in skin.get("parts") or [skin.get("painting", "")]:
        if is_npc_painting(part):
            return True
    return False
