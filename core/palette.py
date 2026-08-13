"""立绘取色：从皮肤素材提取主色调并生成背景 CSS（预览与导出共用同一套逻辑）。

算法与 wallpaper-palette skill 保持一致：
采样(≤8 万像素网格) → 过滤(透明/纯黑/纯白/极灰描边) → 16 级量化分桶取桶内平均色
→ 曼哈顿距离去重(35，不足放宽到 15) → 全部 ×0.7 压暗 → 120° 线性渐变。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

DARKEN = 0.7


def find_palette_source(skin: dict, root) -> Path | None:
    """找到用于取色的素材图片：
    1. static 皮肤优先用官方立绘 painting.png；
    2. spine / live2d 取皮肤资源目录里最大的 PNG 贴图（atlas 页 / model texture）。
    """
    stype = skin.get("type", "")
    asset = skin.get("asset") or {}
    base = Path(root)
    if stype == "static":
        # asset.dir 相对 resources/，兼容 root 为仓库根或 resources 根两种传法
        for d in (base / "resources" / str(asset.get("dir", "")), base / str(asset.get("dir", ""))):
            for name in ("painting.png", "painting.bak.png"):
                p = d / name
                if p.is_file():
                    return p
    for d in (base / "resources" / str(asset.get("dir", "")), base / str(asset.get("dir", ""))):
        if d.is_dir():
            pngs = [f for f in d.rglob("*.png") if f.is_file()]
            if pngs:
                return max(pngs, key=lambda f: f.stat().st_size)
    return None


def extract_palette(png_path, num_colors: int = 4) -> list[str] | None:
    """从立绘 PNG 提取主色调。图片损坏/无法解码时返回 None（调用方自行降级）。"""
    try:
        img = Image.open(png_path).convert("RGBA")
        w, h = img.size
        step = max(1, (w * h) // 80000)
        px = img.load()
        buckets: dict[tuple[int, int, int], list[int]] = {}

        for y in range(0, h, step):
            for x in range(0, w, step):
                r, g, b, a = px[x, y]
                if a < 30:
                    continue
                mx, mn = max(r, g, b), min(r, g, b)
                if mx < 25:  # 纯黑
                    continue
                if mn > 235:  # 纯白
                    continue
                if mx - mn < 12 and (mx < 50 or mn > 200):  # 极灰描边
                    continue
                key = (r >> 4, g >> 4, b >> 4)
                bkt = buckets.get(key)
                if bkt is None:
                    buckets[key] = [r, g, b, 1]
                else:
                    bkt[0] += r
                    bkt[1] += g
                    bkt[2] += b
                    bkt[3] += 1

        total = sum(v[3] for v in buckets.values())
        if total < 20:
            return None

        entries = sorted(buckets.items(), key=lambda kv: kv[1][3], reverse=True)

        def avg(kv) -> tuple[int, int, int]:
            _, (sr, sg, sb, cnt) = kv
            return sr // cnt, sg // cnt, sb // cnt

        def manhattan(c1, c2) -> int:
            return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) + abs(c1[2] - c2[2])

        picked: list[tuple[int, int, int]] = []
        for threshold in (35, 15):  # 第一轮 35，不足则放宽到 15
            if len(picked) >= num_colors:
                break
            for kv in entries:
                if len(picked) >= num_colors:
                    break
                c = avg(kv)
                if all(manhattan(c, p) >= threshold for p in picked):
                    picked.append(c)

        if not picked:
            return None
        return [f"#{int(r * DARKEN):02x}{int(g * DARKEN):02x}{int(b * DARKEN):02x}" for r, g, b in picked]
    except Exception:  # noqa: BLE001
        # 素材损坏/格式异常时取色失败，由调用方回退到固定背景样式
        return None


def fallback_palette(hex_color: str = "#1d3f6e", num_colors: int = 4) -> list[str]:
    """素材缺失/取色失败时的回退调色板（HSV 补饱和/亮度 + 色相偏移）。"""
    import colorsys

    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    hh, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.1:
        s = 0.4
    if v < 0.15:
        v = 0.5
    offsets = [0.0, 0.08, 0.15, 0.45]
    out = []
    for off in offsets[:num_colors]:
        rr, gg, bb = colorsys.hsv_to_rgb((hh + off) % 1.0, s, v)
        out.append(f"#{int(rr * 255 * DARKEN):02x}{int(gg * 255 * DARKEN):02x}{int(bb * 255 * DARKEN):02x}")
    return out


def auto_css(palette: list[str]) -> str:
    """自动取色背景：120° 线性渐变，颜色按调色板均匀分布。"""
    if not palette:
        return "background: linear-gradient(120deg, #1d3f6e, #0e1b33 55%, #13294d);"
    if len(palette) == 1:
        return f"background: {palette[0]};"
    stops = ", ".join(f"{c} {i / (len(palette) - 1) * 100:.0f}%" for i, c in enumerate(palette))
    return f"background: linear-gradient(120deg, {stops});"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha})"


def _linear(palette: list[str], angle: int) -> str:
    if len(palette) == 1:
        return f"background: {palette[0]};"
    stops = ", ".join(f"{c} {i / (len(palette) - 1) * 100:.0f}%" for i, c in enumerate(palette))
    return f"background: linear-gradient({angle}deg, {stops});"


def mode_css(mode: str, palette: list[str] | None, solid_color: str | None = None) -> str:
    """按模式用立绘调色板生成背景 CSS；palette 为空时由调用方回退固定样式。"""
    palette = palette or []
    if not palette:
        return ""
    c0 = palette[0]
    c1 = palette[1] if len(palette) > 1 else c0
    c2 = palette[2] if len(palette) > 2 else c1
    c3 = palette[3] if len(palette) > 3 else c2

    if mode == "solid":
        return f"background: {solid_color or c0};"
    if mode == "gradient":
        return _linear(palette, 135)
    if mode == "monet":
        return (
            "background: "
            f"radial-gradient(60% 70% at 20% 25%, {_rgba(c0, 0.35)}, transparent 60%),"
            f"radial-gradient(55% 65% at 80% 20%, {_rgba(c1, 0.30)}, transparent 60%),"
            f"radial-gradient(70% 80% at 50% 95%, {_rgba(c2, 0.22)}, transparent 60%),"
            f"linear-gradient(160deg, {c0}, #0b0f17);"
        )
    if mode == "frost":
        return (
            "background: "
            f"radial-gradient(45% 55% at 30% 30%, {_rgba(c0, 0.25)}, transparent 60%),"
            f"radial-gradient(45% 55% at 75% 70%, {_rgba(c1, 0.22)}, transparent 60%),"
            f"linear-gradient(180deg, {c0}, #0b0f17);"
        )
    if mode == "star":
        return (
            "background: "
            "radial-gradient(1.5px 1.5px at 20% 30%, rgba(255,255,255,.7), transparent 60%),"
            "radial-gradient(1.5px 1.5px at 60% 15%, rgba(255,255,255,.6), transparent 60%),"
            "radial-gradient(1.5px 1.5px at 80% 45%, rgba(255,255,255,.5), transparent 60%),"
            "radial-gradient(1.5px 1.5px at 40% 70%, rgba(255,255,255,.55), transparent 60%),"
            "radial-gradient(1.5px 1.5px at 90% 80%, rgba(255,255,255,.45), transparent 60%),"
            f"linear-gradient(180deg, {c0}, #080c14);"
        )
    # auto / 默认
    return _linear(palette, 120)
