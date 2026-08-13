# -*- coding: utf-8 -*-
"""从碧蓝航线 wiki 舰船图鉴下载角色头像，并按角色名匹配存到本地。

头像来源：https://wiki.biligame.com/blhx/舰船图鉴 渲染页的 <img>，
文件名规则为 {角色名}头像.jpg（原图直链，单张约 10~20KB）。

产物：
- resources/avatars/{角色名}.jpg          头像图片（按 ships.json 角色名命名）
- resources/metadata/avatars.json         角色名 -> 头像文件名的映射

用法：
  python tools/fetch_avatars.py            # 联网抓取并下载（已有文件自动跳过）
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "resources" / "metadata"
AVATAR_DIR = ROOT / "resources" / "avatars"
AVATAR_MAP = MD / "avatars.json"

WIKI_API = "https://wiki.biligame.com/blhx/api.php"
WIKI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 已知角色名与图鉴头像名的差异（多为联动/译名），头像文件名用图鉴名
NAME_ALIASES = {
    "BLACK★ROCK SHOOTER": "黑岩射手",
    "DEAD MASTER": "死亡主宰",
    "八舞耶倶矢·八舞夕弦": "八舞耶俱矢·八舞夕弦",
}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").lower()
    for a, b in (("倶", "俱"), ("・", "·")):
        s = s.replace(a, b)
    return re.sub(r"[\s_\-·・‐‑‒—―−()（）/\\~～★☆?!？！]", "", s)


def wiki_api(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=WIKI_HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 1.5)
    return {}


def original_url(thumb_url: str) -> str:
    """缩略图 URL -> 原图直链（去掉 /thumb/ 与尺寸段）。"""
    m = re.search(r"/thumb/([a-f0-9])/([a-f0-9]{2})/([^/]+\.(?:jpg|png))", thumb_url)
    if m:
        return f"https://patchwiki.biligame.com/images/blhx/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return thumb_url


def collect_avatars() -> dict[str, str]:
    """返回 {图鉴头像名: 原图URL}。"""
    d = wiki_api({"action": "parse", "page": "舰船图鉴", "prop": "text"})
    html = d.get("parse", {}).get("text", "")
    out: dict[str, str] = {}
    for m in re.finditer(r'<img[^>]+src="([^"]+)"[^>]*>', html):
        url = m.group(1)
        base = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        mm = re.fullmatch(r"(\d+)px-(.+?)头像\.(?:jpg|png)", base, re.I)
        if not mm:
            continue
        name = mm.group(2).strip()
        if not name or "外框" in name:
            continue
        out.setdefault(name, original_url(url))
    return out


def main() -> int:
    ships = json.loads((MD / "ships.json").read_text(encoding="utf-8"))
    ship_norms = {norm(s["name"]): s["name"] for s in ships}
    for alias, wiki_name in NAME_ALIASES.items():
        ship_norms.setdefault(norm(wiki_name), alias)

    print("正在抓取舰船图鉴渲染页…")
    try:
        avatars = collect_avatars()
    except Exception as e:  # noqa: BLE001
        # wiki 偶尔限流/超时：保留现有头像，本次跳过，不阻塞整个更新流程
        print(f"图鉴抓取失败（{e}），本次跳过头像更新，现有头像保持不变")
        return 0
    print(f"图鉴头像：{len(avatars)} 个")

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    tasks = []
    retro_tasks: dict[str, str] = {}  # 基础角色名 -> 改头像URL（基础头像缺失时兜底）
    unmatched = []
    existing = 0
    for wiki_name, url in avatars.items():
        app_name = ship_norms.get(norm(wiki_name))
        if not app_name:
            if wiki_name.endswith("改"):
                base_app = ship_norms.get(norm(wiki_name[:-1]))
                if base_app:
                    retro_tasks.setdefault(base_app, url)
                    continue
            unmatched.append(wiki_name)
            continue
        dest = AVATAR_DIR / f"{app_name}.jpg"
        mapping[app_name] = app_name
        if dest.exists() and dest.stat().st_size > 500:
            existing += 1
            continue
        tasks.append((app_name, url, dest))

    # 基础头像缺失的角色用“改”头像兜底
    for app_name, url in retro_tasks.items():
        if app_name in mapping:
            continue
        dest = AVATAR_DIR / f"{app_name}.jpg"
        mapping[app_name] = app_name
        if dest.exists() and dest.stat().st_size > 500:
            existing += 1
            continue
        tasks.append((app_name, url, dest))

    def download(item):
        app_name, url, dest = item
        try:
            req = urllib.request.Request(url, headers=WIKI_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 500 or not data.startswith(b"\xff\xd8"):
                return app_name, False, "非JPEG"
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return app_name, True, ""
        except Exception as e:  # noqa: BLE001
            return app_name, False, str(e)[:120]
        finally:
            time.sleep(0.05)

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(download, t): t[0] for t in tasks}
        for fut in as_completed(futs):
            name, okk, err = fut.result()
            if okk:
                ok += 1
            else:
                fail += 1
                print(f"  ✗ {name}: {err}")

    AVATAR_MAP.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n已完成：新下载 {ok}，已有 {existing}，失败 {fail}，头像映射 {len(mapping)} 个角色")
    if unmatched:
        print(f"未匹配到角色 {len(unmatched)} 个：")
        for n in sorted(unmatched)[:30]:
            print("  ?", n)
    print(f"产物：{AVATAR_DIR}（{len(list(AVATAR_DIR.glob('*.jpg')))} 张） + {AVATAR_MAP.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
