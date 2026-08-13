"""从 B站 wiki 同步舰船/皮肤元数据 → ships.json / skins.json。

用法: python tools/sync_metadata.py [输出目录] [舰船数量上限]
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://wiki.biligame.com/blhx/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("resources/metadata")
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0 = 全部


def api(params):
    params = {**params, "format": "json", "formatversion": "2"}
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 1.5)


def fetch_ships():
    ships = {}
    offset = 0
    while True:
        q = f"[[分类:舰娘]]|?名称|?阵营|?稀有度|limit=500|offset={offset}"
        data = api({"action": "ask", "query": q})
        res = data.get("query", {}).get("results", {})
        if not res:
            break
        for title, info in res.items():
            po = info.get("printouts", {})
            ships[title] = {
                "name": title,
                "display": info.get("displaytitle") or title,
                "faction": (po.get("阵营") or [""])[0],
                "rarity": (po.get("稀有度") or [""])[0],
            }
        nxt = data.get("query-continue-offset")
        if nxt is None or nxt <= offset:
            break
        offset = nxt
        time.sleep(0.2)
        if LIMIT and len(ships) >= LIMIT:
            break
    return ships


def parse_wikitext(title):
    data = api({"action": "parse", "page": title, "prop": "wikitext"})
    return data.get("parse", {}).get("wikitext", "")


def extract(wt):
    def field(name):
        m = re.search(rf"^\|\s*{name}\s*=\s*(.*)$", wt, re.M)
        return m.group(1).strip() if m else ""

    titles = re.findall(r"^\|\s*标题(\d+)\s*=\s*(.+)$", wt, re.M)
    titles.sort(key=lambda x: int(x[0]))
    return {
        "hull": field("类型"),
        "no": field("编号"),
        "en": field("英文名"),
        "default_skin": field("名称"),
        "skins": [t[1].strip() for t in titles],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ships = fetch_ships()
    print("ships:", len(ships))
    out_ships, out_skins = [], []
    for i, (title, s) in enumerate(ships.items()):
        try:
            wt = parse_wikitext(title)
        except Exception as e:  # noqa: BLE001
            print("skip", title, e)
            continue
        ext = extract(wt)
        out_ships.append({**s, "hull": ext["hull"], "no": ext["no"], "en": ext["en"]})
        out_skins.append({"ship": title, "name": ext["default_skin"] or title, "bundle": ""})
        for idx, name in enumerate(ext["skins"]):
            out_skins.append({"ship": title, "name": name, "bundle": f"_{idx + 2}"})
        time.sleep(0.12)
        if (i + 1) % 50 == 0:
            print("progress", i + 1)
        if LIMIT and i + 1 >= LIMIT:
            break
    (OUT / "bwiki_ships.json").write_text(
        json.dumps(out_ships, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT / "skins.json").write_text(
        json.dumps(out_skins, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("done:", len(out_ships), "ships,", len(out_skins), "skins ->", OUT)


if __name__ == "__main__":
    main()