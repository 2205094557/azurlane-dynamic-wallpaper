"""角色/皮肤语音：官方 CDN CriWare cue 包下载 → vgmstream 逐条解码为 wav。

链路（CN 服实测）：
  网关 command 10800 → $cvhash$... → hash 清单（cue/cv-{shipId}.b,大小,md5）
  → resource/{md5} 下载 cue 包 → vgmstream-cli 解码为 resources/voice/{shipId}/{cue}.wav

cue 名 = 台词分类（login / home / touch_head / touch_1 / touch_2 / main_N / *_ex1100 L2D 变体）。
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "resources" / "metadata"
VOICE_DIR = ROOT / "resources" / "voice"  # {shipId}/{cue}.wav
BUNDLES_DIR = ROOT / "resources" / "bundles" / "voice"
VGMSTREAM_DIR = ROOT / "tools" / "vgmstream"
VGMSTREAM_CLI = VGMSTREAM_DIR / "vgmstream-cli.exe"
VOICE_SHIPS = METADATA / "voice_ships.json"

# cue 名 → 互动动作的播放映射（带 _ex1100 时优先用 L2D 专属变体）
CUE_FOR_LABEL = {
    "touch_head": "touch_head",
    "touch_body": "touch_1",
    "touch_special": "touch_2",
    "login": "login",
    "home": "home",
}

# 待机（idle/main）语音 cue 前缀：main_N
IDLE_CUE_RE = re.compile(r"^main_\d+$")


def ship_id_for(painting: str) -> int | None:
    """painting（如 liekexingdunii_2）→ 船 key → shipGroupId。"""
    if not painting:
        return None
    key = re.sub(r"_\d+$", "", painting).lower()
    try:
        data = json.loads(VOICE_SHIPS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    gid = data.get(key)
    return int(gid) if gid else None


def words_for(painting: str) -> dict:
    """该皮肤互动台词的文本映射（headtouch/touch/touch2/login/home/main）。

    voice_words.json 按 painting 收录，部分船（如 U-2501）数据源缺失；
    查不到时回退到船 key（painting 去 _N 后缀），保证基础皮能用。
    若当前皮肤缺 headtouch 文本，则从同船其它皮肤（含基础皮）借用，
    避免「有语音没台词」。
    """
    if not painting:
        return {}
    try:
        data = json.loads((METADATA / "voice_words.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    hit = data.get(painting)
    if not hit:
        key = re.sub(r"_\d+$", "", painting).lower()
        hit = data.get(key, {})
    if not isinstance(hit, dict):
        hit = {}
    # 缺 headtouch 时：同船其它皮肤（前缀相同，含基础皮）若有，借用该文本
    if not hit.get("headtouch"):
        prefix = re.sub(r"_\d+$", "", painting).lower()
        for k, v in data.items():
            if isinstance(v, dict) and v.get("headtouch") and k.startswith(prefix):
                hit = dict(hit)
                hit["headtouch"] = v["headtouch"]
                break
    return hit


def remove_voice(ship_id: int) -> list[str]:
    """删除该船语音（转换产物 + cue 包），返回删除的文件列表。"""
    removed: list[str] = []
    d = voice_dir(ship_id)
    if d.is_dir():
        for f in d.rglob("*"):
            if f.is_file():
                f.unlink(missing_ok=True)
                removed.append(str(f))
        try:
            d.rmdir()
        except OSError:
            pass
    b = BUNDLES_DIR / f"cv-{ship_id}.b"
    if b.exists():
        b.unlink(missing_ok=True)
        removed.append(str(b))
    return removed


def voice_dir(ship_id: int) -> Path:
    return VOICE_DIR / str(ship_id)


def voice_ship_ids() -> list[int]:
    """本地已下载语音的 shipId 列表。"""
    if not VOICE_DIR.is_dir():
        return []
    return [int(d.name) for d in VOICE_DIR.iterdir() if d.is_dir() and d.name.isdigit()]


def clean_voice(keep_ids: set[int] | None = None) -> dict:
    """清理已下载语音（转换产物 + cue 包）。

    keep_ids：需要保留的 shipId 集合；None 表示全部删除。
    返回 {"removed_ships": n, "removed_files": n}。
    """
    removed_ships = 0
    removed_files = 0
    for sid in voice_ship_ids():
        if keep_ids is not None and sid in keep_ids:
            continue
        removed_files += len(remove_voice(sid))
        removed_ships += 1
    return {"removed_ships": removed_ships, "removed_files": removed_files}


def cue_file(ship_id: int, cue: str) -> Path:
    return voice_dir(ship_id) / f"{cue}.wav"


def voice_cues(ship_id: int) -> list[str]:
    """本地已转换的 cue 名列表。"""
    d = voice_dir(ship_id)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.wav"))


def ship_for_painting(painting: str) -> str | None:
    """painting → 船名（skins.json）。"""
    if not painting:
        return None
    try:
        data = json.loads((METADATA / "skins.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for s in data:
        if s.get("painting") == painting:
            return s.get("ship")
    return None


def first_l2d_painting(ship: str) -> str | None:
    """该船第一个（实装最早）L2D 皮肤 painting；无 L2D 皮肤返回 None。

    碧蓝每船只有一个主语音包 cv-{shipId}.b，皮肤专属语音仅一套 _ex1100，
    属于实装最早的 L2D 皮肤；其余 L2D 皮肤互动使用基础语音。
    """
    if not ship:
        return None
    try:
        data = json.loads((METADATA / "skins.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    l2d = [s for s in data if s.get("ship") == ship and s.get("type") == "live2d" and s.get("painting")]
    if not l2d:
        return None
    def rank(s: dict) -> int:
        m = re.search(r"_(\d+)$", s.get("bundle") or "")
        return int(m.group(1)) if m else 0
    return min(l2d, key=rank).get("painting")


def skin_voice_n(painting: str) -> int:
    """painting（u2501_2）→ 换装序号 N（1=第一个换装；0=基础皮）。

    cv-{shipId}.b 里 {base}_{N} 是第 N 个换装皮肤的专属语音（touch_1_1=touch_1_2…）。
    """
    m = re.search(r"_(\d+)$", painting or "")
    return (int(m.group(1)) - 1) if m else 0


_VOICE_MAP_CACHE: dict | None = None


def voice_skin_map() -> dict:
    """皮肤 → {base: cue} 映射（tools/build_voice_skin_map.py 生成）。

    每艘船的语音编号是各 base 独立分配的（login 表/touch 表各自编号），
    与 painting 后缀无简单对应；映射表按「语音时长↔台词字数」排序匹配生成。
    """
    global _VOICE_MAP_CACHE
    if _VOICE_MAP_CACHE is None:
        try:
            _VOICE_MAP_CACHE = json.loads((METADATA / "voice_skin_map.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _VOICE_MAP_CACHE = {}
    return _VOICE_MAP_CACHE


def pick_cue(ship_id: int, base: str, painting: str | None = None) -> str | None:
    """按基础名挑该皮肤的 cue。

    优先级：voice_skin_map 映射（时长匹配确认的皮肤专属）→ {base}_{N}
    （bundle-1 连续规则兜底）→ {base}_ex1100（L2D 互动兜底）→ {base}。
    注意 {base}_1 是第一个换装皮肤的语音，不能当通用回退。
    """
    cues = set(voice_cues(ship_id))
    if painting:
        m = (voice_skin_map().get(painting) or {}).get(base)
        if m and m in cues:
            return m
    skin_n = skin_voice_n(painting or "")
    if skin_n and f"{base}_{skin_n}" in cues:
        return f"{base}_{skin_n}"
    if f"{base}_ex1100" in cues:
        return f"{base}_ex1100"
    if base in cues:
        return base
    return None


def export_voice(ship_id: int, dest_dir: Path, painting: str | None = None) -> dict | None:
    """复制互动语音（pick + main_*）到壁纸项目 assets/voice，返回运行时配置。

    返回 {"dir": "assets/voice", "pick": {base: cue}, "mains": [cue...]}；无语音返回 None。
    painting 传当前皮肤：按语音映射表取该皮肤专属语音。
    """
    import shutil
    cues = set(voice_cues(ship_id))
    if not cues:
        return None
    pick = {}
    for base in CUE_FOR_LABEL.values():
        c = pick_cue(ship_id, base, painting=painting)
        if c:
            pick[base] = c
    mains = sorted(c for c in cues if IDLE_CUE_RE.match(c))
    dest_dir.mkdir(parents=True, exist_ok=True)
    for cue in list(pick.values()) + mains:
        src = cue_file(ship_id, cue)
        if src.exists():
            shutil.copy2(src, dest_dir / src.name)
    return {"dir": "assets/voice", "pick": pick, "mains": mains}


def _vgmstream(args: list[str]) -> str:
    """调用 vgmstream-cli（DLL 需与 exe 同目录）。"""
    import os
    env = dict(os.environ)
    env["PATH"] = str(VGMSTREAM_DIR) + os.pathsep + env.get("PATH", "")
    # vgmstream-cli 是控制台 exe，不带标志时每个 cue 解码都会闪一个黑框
    # （语音包解码逐条调用，看起来就是下载时疯狂跳黑框）
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(
        [str(VGMSTREAM_CLI), *args],
        capture_output=True, text=True, env=env, timeout=600,
        creationflags=creationflags,
        # 语音元数据（cue 名等）可能是非 GBK 编码（日文/Shift-JIS），
        # 系统默认 GBK 解码会 UnicodeDecodeError 崩掉请求线程
        encoding="utf-8", errors="replace",
    )
    return r.stdout or r.stderr


def _cue_names(acb: Path) -> list[str]:
    """用 -m 逐个取 stream name（stream count 从元数据拿）。"""
    out = _vgmstream(["-m", str(acb)])
    m = re.search(r"stream count: (\d+)", out)
    count = int(m.group(1)) if m else 0
    names: list[str] = []
    for i in range(1, count + 1):
        o = _vgmstream(["-m", "-s", str(i), str(acb)])
        mm = re.search(r"stream name: (.+)", o)
        names.append(mm.group(1).strip() if mm else f"cue{i}")
    return names


def convert_acb(acb: Path, out_dir: Path, cancel_event: threading.Event | None = None) -> list[str]:
    """把 CriWare cue 包逐条解码为 {cue}.wav，返回 cue 名列表。

    vgmstream 按扩展名识别格式，.b 会识别失败，这里用临时 .acb 副本。
    """
    acb_path = acb.with_suffix(".acb")
    if not acb_path.exists():
        import shutil
        shutil.copy2(acb, acb_path)
    names = _cue_names(acb_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    for i, name in enumerate(names, 1):
        if cancel_event and cancel_event.is_set():
            break
        wav = out_dir / f"{name}.wav"
        if not wav.exists():
            _vgmstream(["-o", str(wav), "-s", str(i), str(acb_path)])
        if wav.exists() and wav.stat().st_size > 0:
            done.append(name)
    return done


def download_voice(
    ship_id: int,
    info=None,
    cancel_event: threading.Event | None = None,
    emit=None,
) -> Path | None:
    """下载该船语音并转换为 cue wav，返回语音目录；失败返回 None。

    info：可传 cdn.handshake() 结果复用版本信息；不传则内部握手。
    emit：进度回调 emit(stage, detail)。
    """
    from plugins.sources.cdn import CdnSource  # 延迟导入避免循环

    def stage(s, d=""):
        if emit:
            emit(s, d)
    source = CdnSource()
    if info is None:
        info = source.handshake("CN")
    cdn = info.cdn
    raw = info.raw_strings.get("cvhash") or info.versions.get("cvhash")
    if not raw or not cdn:
        stage("语音版本获取失败")
        return None

    out_dir = voice_dir(ship_id)
    if out_dir.is_dir() and any(out_dir.glob("*.wav")):
        return out_dir  # 已有语音

    stage("正在获取语音清单", f"船 {ship_id}")
    csv = source.fetch_hash_csv(cdn, raw)
    target = None
    for line in csv.splitlines():
        parts = line.split(",")
        if len(parts) >= 3 and parts[0] == f"cue/cv-{ship_id}.b":
            target = parts
            break
    if not target:
        stage("该船无独立语音库", f"cv-{ship_id}.b")
        return None
    _, size, md5 = target[0], int(target[1]), target[2]

    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    acb = BUNDLES_DIR / f"cv-{ship_id}.b"
    stage("正在下载语音包", f"cv-{ship_id}.b ({size // 1024}KB)")
    ok = source.download_asset(cdn, md5, acb, size, cancel_event=cancel_event)
    if not ok or not acb.exists():
        stage("语音包下载失败", f"cv-{ship_id}.b")
        return None

    stage("正在解码语音", "vgmstream")
    try:
        convert_acb(acb, out_dir, cancel_event=cancel_event)
    except Exception as e:  # noqa: BLE001
        stage("语音解码失败", str(e)[:80])
        return None
    stage("语音就绪", f"{ship_id} 共 {len(list(out_dir.glob('*.wav')))} 条")
    return out_dir
