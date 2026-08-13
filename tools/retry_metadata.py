"""重试 bwiki 风控跳过的舰船，合并进 ships.json / skins.json。"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://wiki.biligame.com/blhx/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MD = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("resources/metadata")

MISSING = [
    "回声", "圣哈辛托", "圣塔菲", "抚顺", "拉·加利索尼埃", "拉德福特",
    "火枪手", "霞飞", "吕佐夫", "云龙", "鞍山", "顽皮", "飞云", "香格里拉", "马塞纳",
    "奇尔沙治",
]


def api(params):
    params = {**params, "format": "json", "formatversion": "2"}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


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
    ships = json.loads((MD / "ships.json").read_text(encoding="utf-8"))
    skins = json.loads((MD / "skins.json").read_text(encoding="utf-8"))
    existing = {s["name"] for s in ships}
    ok, fail = 0, []
    for title in MISSING:
        if title in existing:
            continue
        wt = None
        for attempt in range(3):
            try:
                wt = parse_wikitext(title)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", title, attempt, e)
                time.sleep(5 + attempt * 5)
        if wt is None:
            fail.append(title)
            continue
        ext = extract(wt)
        ships.append({
            "name": title, "display": title, "faction": "", "rarity": "",
            "hull": ext["hull"], "no": ext["no"], "en": ext["en"],
        })
        skins.append({"ship": title, "name": ext["default_skin"] or title, "bundle": ""})
        for idx, name in enumerate(ext["skins"]):
            skins.append({"ship": title, "name": name, "bundle": f"_{idx + 2}"})
        print("merged:", title, len(ext["skins"]), "skins")
        ok += 1
        time.sleep(3)
    (MD / "ships.json").write_text(json.dumps(ships, ensure_ascii=False, indent=1), encoding="utf-8")
    (MD / "skins.json").write_text(json.dumps(skins, ensure_ascii=False, indent=1), encoding="utf-8")
    print("merged:", ok, "failed:", fail)


if __name__ == "__main__":
    main()