"""从碧蓝航线 bwiki 补抓缺失的角色/皮肤语音台词，写入 voice_words.json。

用法：python tools/fetch_voice_words.py <船名或URL> [目标painting]
按 bwiki 页面结构解析 <tr data-key> 语音块，把皮肤组（desc 之后的块）写为该皮肤的
headtouch/touch/touch2/login/home/main 台词。

bwiki 有频控，单次请求失败（验证页/空页）会退避重试。
"""

from __future__ import annotations

import html as html_mod
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS_FILE = ROOT / "resources" / "metadata" / "voice_words.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 皮肤组语音块：desc 之后的行都属于该皮肤（含 desc 自身是皮肤描述，跳过）
SKIN_GROUP_START = "desc"
# 互动台词分类 → voice_words.json 字段
CAT_MAP = {
    "headtouch": "headtouch",
    "touch": "touch",
    "touch2": "touch2",
    "login": "login",
    "home": "home",
    "main": "main",
}


def fetch(url: str, tries: int = 5) -> str:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            text = raw.decode("utf-8", errors="ignore")
            if "ship_word_line" in text:
                return text
            print(f"  尝试 {i + 1}: 空页/验证页（{len(text)} 字节），退避 {20 * (i + 1)}s…")
        except Exception as e:  # noqa: BLE001
            print(f"  尝试 {i + 1}: {e}，退避 {20 * (i + 1)}s…")
        time.sleep(20 * (i + 1))
    return ""


def parse_blocks(html_text: str) -> list[tuple[str, list[str]]]:
    """解析出 [(key, [台词...])] 语音块列表。"""
    out = []
    for key, body in re.findall(r'<tr data-key="([^"]+)"[^>]*>(.*?)</tr>', html_text, re.S):
        lines = re.findall(r'data-lang="zh"[^>]*>\s*(.*?)\s*</p>', body, re.S)
        lines = [html_mod.unescape(re.sub(r"<[^>]+>", "", l)).strip() for l in lines]
        lines = [l for l in lines if l]
        if lines:
            out.append((key, lines))
    return out


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    page = sys.argv[1]
    painting = sys.argv[2] if len(sys.argv) > 2 else None
    if not page.startswith("http"):
        page = "https://wiki.biligame.com/blhx/" + urllib.parse.quote(page)
    print(f"抓取 {page} …")
    text = fetch(page)
    if not text:
        print("失败：未能获取页面（可能是频控，稍后重试）")
        sys.exit(2)
    blocks = parse_blocks(text)
    if not blocks:
        print("失败：页面无语音数据")
        sys.exit(2)

    # 基础组（第一个 desc 之前的行）+ 皮肤组（desc 之后的块）
    base: dict[str, list[str]] = {}
    skin: dict[str, list[str]] = {}
    target = base
    for key, lines in blocks:
        if key == SKIN_GROUP_START:
            target = skin  # 皮肤描述开始 → 后续都是该皮肤语音
            continue
        if target is not skin:
            target.setdefault(key, []).extend(lines)
        else:
            skin.setdefault(key, []).extend(lines)

    words: dict = {}
    for cat, field in CAT_MAP.items():
        v = skin.get(cat)
        if not v:
            continue
        words[field] = v if field == "main" else v[0]  # main 保留整组数组，其余取首条
    if not words:
        print("失败：皮肤组无互动台词（headtouch/touch/touch2/login/home/main 均缺失）")
        sys.exit(2)
    if "main" not in words:
        words["main"] = []
    # 补充基础组 main（皮肤 main 缺失时）
    if not words.get("main") and base.get("main"):
        words["main"] = base["main"]

    data = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
    if painting is None:
        painting = input("目标 painting（如 u2501_2）：").strip()
    data[painting] = words
    WORDS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {painting}: {json.dumps(words, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
