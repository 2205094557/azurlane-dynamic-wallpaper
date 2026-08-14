"""生成 皮肤 → 互动语音 cue 映射（voice_skin_map.json）。

背景：cv-{shipId}.b 里 {base}_{N} 是各换装皮肤的专属语音，但 N 与
painting 后缀（bundle 序号）不是简单对应（如 企业 qiye_9→login_11、
qiye_10→login_10）。用「语音时长 ↔ 台词文本长度」排序匹配确定映射：
同一句话的语音时长与文本字数强相关，排序一致即可靠。

只写入一致性 ≥ MIN_AGREE 的映射；不满足的船运行时回退
「N=bundle-1 连续规则 → _ex1100 → 基础」。

用法：python tools/build_voice_skin_map.py
"""

from __future__ import annotations

import json
import re
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.voice import voice_cues, ship_id_for, VOICE_DIR  # noqa: E402

METADATA = ROOT / "resources" / "metadata"
MIN_AGREE = 0.85  # 排序一致性阈值（Kendall tau 简化版），低置信不写入
BASES = [("login", "login"), ("touch_1", "touch"), ("touch_2", "touch2"), ("home", "home"), ("touch_head", "headtouch")]


def cue_duration(gid: int, cue: str) -> float | None:
    p = VOICE_DIR / str(gid) / f"{cue}.wav"
    if not p.exists():
        return None
    try:
        with wave.open(str(p)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:  # noqa: BLE001
        return None


def agree_score(durs: list[float], lens: list[int]) -> float:
    """Kendall tau 简化：同序对占比。durs/lens 已各自排序。"""
    n = len(durs)
    if n < 3:
        return 1.0
    agree = 0
    for i in range(n):
        for j in range(i + 1, n):
            if (durs[i] > durs[j]) == (lens[i] > lens[j]):
                agree += 1
    return agree / (n * (n - 1) / 2)


def main() -> None:
    skins = json.loads((METADATA / "skins.json").read_text(encoding="utf-8"))
    words = json.loads((METADATA / "voice_words.json").read_text(encoding="utf-8"))

    # 船 → 该船有台词文本的换装皮肤（painting 带 _N 后缀）
    by_ship: dict[str, list[dict]] = {}
    for s in skins:
        p = s.get("painting") or ""
        if s.get("ship") and re.search(r"_\d+$", p):
            by_ship.setdefault(s["ship"], []).append(s)

    mapping: dict[str, dict[str, str]] = {}
    used: dict[str, int] = {}
    for ship, skin_list in by_ship.items():
        gid = ship_id_for(skin_list[0]["painting"])
        if not gid:
            continue
        cues_all = set(voice_cues(gid))
        for base, words_key in BASES:
            n_cues = sorted(c for c in cues_all if re.fullmatch(rf"{base}_\d+", c))
            if not n_cues:
                continue
            pairs = []
            for s in skin_list:
                t = words.get(s["painting"], {}).get(words_key)
                if t:
                    pairs.append((s["painting"], len(t)))
            if not pairs:
                continue
            durs = [(cue_duration(gid, c) or 0, c) for c in n_cues]
            durs.sort(reverse=True)
            pairs.sort(key=lambda x: x[1], reverse=True)
            n = min(len(durs), len(pairs))
            if n < 3:
                continue  # 样本太少，排序不可靠，交给运行时默认规则
            score = agree_score([d for d, _ in durs[:n]], [l for _, l in pairs[:n]])
            if score < MIN_AGREE:
                continue
            for (_, cue), (painting, _) in zip(durs[:n], pairs[:n]):
                mapping.setdefault(painting, {})[base] = cue
                used[painting] = used.get(painting, 0) + 1

    out = METADATA / "voice_skin_map.json"
    out.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {out.name}: {len(mapping)} 个皮肤映射")

    # 抽查关键船
    for p in ("xinnong_3", "xinnong_4", "xinnong_5", "xinnong_6", "qiye_7", "qiye_9", "qiye_10"):
        m = mapping.get(p, {})
        print(f"  {p}: " + " ".join(f"{k}={v}" for k, v in sorted(m.items())))


if __name__ == "__main__":
    main()
