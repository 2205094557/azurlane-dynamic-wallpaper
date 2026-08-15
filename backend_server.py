"""本地后端 API 服务：提供官方 CDN 下载等接口，供前端（浏览器/桌面）调用。

启动: python backend_server.py [端口]   （默认 8766）
"""

from __future__ import annotations

import json
import hashlib
import os
import queue
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.config import Config  # noqa: E402
from core.library import Library  # noqa: E402
from core.locks import named_lock  # noqa: E402
from core.metadata import Metadata  # noqa: E402
from core.palette import extract_palette, fallback_palette, find_palette_source, mode_css  # noqa: E402
from core.registry import Registry  # noqa: E402
from core.we_integration import apply_wallpaper  # noqa: E402
from core.applog import setup_logging  # noqa: E402

registry = Registry(ROOT / "plugins").discover()
metadata = Metadata(ROOT / "resources" / "metadata")
library = Library(ROOT / "resources" / "library.db")
config = Config(ROOT / "resources" / "config.json")
cdn = registry.get("sources", "cdn")
if config.get("proxy"):
    cdn.proxy = config.get("proxy") or None
logger = setup_logging()

# ---- 下载阶段事件推送（SSE）：前端右下角卡片实时显示 下载/合成/同步 等阶段 ----
_EVENT_QUEUES: list[queue.Queue] = []
_EVENT_LOCK = threading.Lock()


def _broadcast(name: str, data: dict) -> None:
    payload = f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _EVENT_LOCK:
        for q in _EVENT_QUEUES:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


def _emit_stage(stage: str, **extra) -> None:
    _broadcast("stage", {"stage": stage, **extra})

_META_MTIMES: dict[str, float] = {}
# 批量下载取消：前端带 download_id 发起下载，点取消时置位对应 Event，
# 下载循环按 chunk 检查，能快速停止正在进行的 CDN 下载（而非等整个文件下完）。
_CANCEL_LOCK = threading.Lock()
_CANCEL_EVENTS: dict[str, threading.Event] = {}


def _register_cancel(download_id: str) -> threading.Event:
    ev = threading.Event()
    with _CANCEL_LOCK:
        _CANCEL_EVENTS[download_id] = ev
    return ev


def _unregister_cancel(download_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(download_id, None)


def cancel_download(download_id: str) -> bool:
    with _CANCEL_LOCK:
        ev = _CANCEL_EVENTS.get(download_id)
    if ev is not None:
        ev.set()
        return True
    return False
# dependencies 包与本地索引是共享文件，并发下载时多线程同时写会损坏/丢数据，必须串行化。
# 用 OS 级命名互斥体（打包版模块可能多实例，threading.Lock 不共享）。
_DEPS_LOCK = named_lock("azurlane_dependencies")
_INDEX_LOCK = named_lock("azurlane_local_index")
# run_tool 与提取器都会改写全局 sys.argv，必须共用同一把锁（与 static/live2d 提取器同名）。
_TOOL_LOCK = named_lock("azurlane_sysargv")


def ensure_fresh_metadata() -> None:
    """每个请求前调用：元数据 JSON 被外部工具/脚本改动（mtime 变化）时自动重载，
    保证界面看到的数据和后端 API（下载/导出/取色）永远一致，不会出现
    “界面有皮肤、下载却说皮肤不存在”的旧内存数据问题。"""
    changed = False
    for name in ("ships.json", "skins.json", "local_skins.json"):
        p = ROOT / "resources" / "metadata" / name
        mt = p.stat().st_mtime if p.exists() else 0.0
        if _META_MTIMES.get(name) != mt:
            _META_MTIMES[name] = mt
            changed = True
    if changed:
        metadata.reload()
        refresh_library()


def refresh_library() -> None:
    library.import_metadata(metadata.ships(), metadata.skins(), metadata.local_skins())


refresh_library()


def get_config() -> dict:
    """返回当前配置（含代理设置）。"""
    return {"ok": True, "config": config.data}


def set_config(patch: dict) -> dict:
    """更新配置并立即生效（目前只有代理）。"""
    patch = patch or {}
    if "proxy" in patch:
        proxy = (patch.get("proxy") or "").strip()
        config.set("proxy", proxy)
        cdn.proxy = proxy or None
    return {"ok": True, "config": config.data}


def resolve_skin(ship: str, bundle: str, name: str | None = None) -> dict | None:
    hits = [s for s in metadata.skins() if s.get("ship") == ship and s.get("bundle") == bundle]
    if not hits:
        return None
    if name is None:
        return hits[0]
    for s in hits:
        if s.get("name") == name:
            return s
    # 名字对不上（占位名/旧名）：仅当 ship+bundle 唯一候选时容忍，
    # 避免 DOA 联动等“同 key 多皮肤”误配。
    return hits[0] if len(hits) == 1 else None


def downloaded_with_painting() -> list[dict]:
    out = []
    for s in library.downloaded_skins():
        skin = resolve_skin(s["ship"], s["bundle"], s.get("name"))
        out.append({**s, "painting": (skin or {}).get("painting", "")})
    return out


def skin_files(skin: dict) -> list[Path]:
    """返回该皮肤对应的本地 bundle 与提取产物路径。"""
    painting = skin.get("painting", "")
    stype = skin.get("type", "")
    b = ROOT / "resources" / "bundles"
    e = ROOT / "resources" / "extracted"
    paths: list[Path] = []
    if stype == "spine":
        paths += [b / "spinepainting" / painting, b / "spinepainting" / f"{painting}_res", e / "spine" / painting]
    elif stype == "live2d":
        paths += [b / "live2d" / painting, e / "live2d" / painting]
    else:
        paths += [b / "painting" / painting, b / "painting" / f"{painting}_tex", e / "static" / painting]
        try:
            from plugins.extractors.static import get_dependencies

            dep = get_dependencies(str(b / "dependencies"))
            for d in dep.get(f"painting/{painting}", []):
                if d.startswith("painting/"):
                    paths.append(b / d)
        except Exception:  # noqa: BLE001
            pass
    return [p for p in paths if p.exists()]


def delete_skin_files(ship: str, bundle: str, name: str | None = None) -> dict:
    skin = resolve_skin(ship, bundle, name)
    if not skin:
        return {"ok": False, "error": "皮肤不存在"}
    removed = [str(p) for p in skin_files(skin)]
    for p in skin_files(skin):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)
    run_tool("build_local_index", timeout=120)
    metadata.reload()
    refresh_library()
    # 语音联动：该船已无其他已下载皮肤时，删除其语音（转换产物 + cue 包）
    try:
        from core import voice as voice_mod
        ship_id = voice_mod.ship_id_for((skin or {}).get("painting", ""))
        if ship_id:
            still = [
                s for s in downloaded_with_painting()
                if s.get("ship") == ship and s.get("painting") != (skin or {}).get("painting")
            ]
            if not still:
                removed.extend(voice_mod.remove_voice(ship_id))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "removed": removed}


def clear_all_downloads() -> dict:
    removed = []
    for sub in ("bundles", "extracted"):
        d = ROOT / "resources" / sub
        if d.is_dir():
            for child in d.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))
    run_tool("build_local_index", timeout=120)
    metadata.reload()
    refresh_library()
    return {"ok": True, "removed": removed}


def _read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def run_tool(name: str, args: list[str] | None = None, timeout: int = 600) -> tuple[int, bytes, bytes]:
    """进程内运行 tools/ 下的脚本模块（打包后无法再用 sys.executable 起子进程）。

    tools 模块没有 __init__.py，按文件路径动态加载，避免引入包结构改动。
    """
    with _TOOL_LOCK:
        import contextlib
        import importlib.util
        import io

        path = ROOT / "tools" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"_pack_tool_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old_argv = sys.argv
        sys.argv = [name] + (args or [])
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = mod.main() or 0
        finally:
            sys.argv = old_argv
        out = buf.getvalue().encode("utf-8", "ignore")
        return rc, out, b""


def finish_metadata_update() -> None:
    """同步完成后重建本地索引并刷新内存元数据/资源库。"""
    run_tool("build_local_index", timeout=120)
    metadata.reload()
    refresh_library()


def run_metadata_update() -> dict:
    """增量更新元数据：CDN 新皮肤 → bwiki 皮肤名 → 图鉴中文名，全自动写入并重建。"""
    report: dict = {"ok": True, "steps": {}}
    # 1) CDN 增量：检测新皮肤并写入官方皮肤表
    rc, out, err = run_tool("update_metadata", ["--apply"], timeout=600)
    report["steps"]["cdn"] = {
        "ok": rc == 0,
        "output": out.decode("utf-8", "ignore")[-3000:],
        "error": err.decode("utf-8", "ignore")[-800:],
    }
    if not report["steps"]["cdn"]["ok"]:
        report["ok"] = False
    # 2) 图鉴同步：以舰船图鉴/换装图鉴为准重建 ships/skins 中文名
    rc, out, err = run_tool("sync_wiki_catalog", timeout=300)
    report["steps"]["wiki"] = {
        "ok": rc == 0,
        "output": out.decode("utf-8", "ignore")[-3000:],
        "error": err.decode("utf-8", "ignore")[-800:],
    }
    if not report["steps"]["wiki"]["ok"]:
        report["ok"] = False
    # 3) 图鉴头像：下载舰船图鉴头像并匹配到角色
    rc, out, err = run_tool("fetch_avatars", timeout=600)
    report["steps"]["avatars"] = {
        "ok": rc == 0,
        "output": out.decode("utf-8", "ignore")[-2000:],
        "error": err.decode("utf-8", "ignore")[-800:],
    }
    if not report["steps"]["avatars"]["ok"]:
        report["ok"] = False
    finish_metadata_update()
    rp = ROOT / "resources" / "metadata" / "update_report.json"
    if rp.exists():
        report["cdn_report"] = _read_json(rp, {})
    wp = ROOT / "resources" / "metadata" / "wiki_sync_report.json"
    if wp.exists():
        report["wiki_report"] = _read_json(wp, {})
    return report


def run_wiki_sync() -> dict:
    """仅从两个图鉴页同步角色/皮肤中文名（不做 CDN 检查）。"""
    rc, out, err = run_tool("sync_wiki_catalog", timeout=300)
    rc2, out2, err2 = run_tool("fetch_avatars", timeout=600)
    finish_metadata_update()
    report: dict = {
        "ok": rc == 0 and rc2 == 0,
        "returncode": rc,
        "output": out.decode("utf-8", "ignore")[-3000:],
        "error": err.decode("utf-8", "ignore")[-800:],
        "avatars_output": out2.decode("utf-8", "ignore")[-1500:],
        "avatars_error": err2.decode("utf-8", "ignore")[-500:],
    }
    wp = ROOT / "resources" / "metadata" / "wiki_sync_report.json"
    if wp.exists():
        report["wiki_report"] = _read_json(wp, {})
    return report


def local_skin_asset(ship: str, bundle: str, name: str | None = None) -> dict | None:
    hits = [
        loc for loc in metadata.local_skins()
        if loc.get("ship") == ship and loc.get("bundle") == bundle
    ]
    if not hits:
        return None
    if name is None:
        return hits[0].get("asset")
    for loc in hits:
        if loc.get("name") == name:
            return loc.get("asset")
    return hits[0].get("asset") if len(hits) == 1 else None


ALIGN_MAP = {
    "center": 0,
    "left-top": 1,
    "right-top": 2,
    "left-bottom": 3,
    "right-bottom": 4,
}


def _export_project(ship: str, bundle: str, name: str | None, options: dict) -> str:
    """生成 WE 壁纸项目，返回项目目录。"""
    skin = resolve_skin(ship, bundle, name)
    if not skin:
        raise ValueError(f"皮肤不存在: {ship}/{bundle}")
    asset = local_skin_asset(ship, bundle, name)
    if not asset:
        raise ValueError("该皮肤尚未下载，请先下载后再导出")
    stype = skin.get("type", "")
    if stype not in ("spine", "live2d", "static"):
        raise ValueError(f"皮肤类型 {stype} 不支持导出壁纸")
    exporter = registry.get(
        "exporters",
        {
            "spine": "wallpaper_spine",
            "live2d": "wallpaper_live2d",
            "static": "wallpaper_static",
        }[stype],
    )
    if exporter is None:
        raise ValueError("导出插件未注册")
    opts = options or {}
    try:
        proj = exporter.export(
            {**skin, "asset": asset},
            {
                "root": str(ROOT),
                "bg": opts.get("bg", "monet"),
                "bgColor": opts.get("bgColor"),
                "scale": int(opts.get("scale", 100) or 100),
                "offsetX": int(opts.get("offsetX", 0) or 0),
                "offsetY": int(opts.get("offsetY", 0) or 0),
                "alignment": ALIGN_MAP.get(str(opts.get("alignment", "center")), 0),
                "animation": opts.get("animation", ""),
                "animations": opts.get("animations") or [],
            },
            str(ROOT / "resources" / "wallpapers"),
        )
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"导出失败: {e}") from e
    return proj


def export_skin(ship: str, bundle: str, name: str | None, options: dict) -> dict:
    """生成 WE 壁纸项目并打开所在文件夹（手动拖入 Wallpaper Engine）。"""
    try:
        proj = _export_project(ship, bundle, name, options)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        os.startfile(str(Path(proj)))  # noqa: S606
        opened = True
    except Exception as e:  # noqa: BLE001
        opened = False
        return {
            "ok": True,
            "project": proj,
            "opened": False,
            "error": f"导出成功但打开文件夹失败: {e}",
        }
    return {
        "ok": True,
        "project": proj,
        "opened": opened,
        "message": "导出完成，已打开项目文件夹，请把 index.html 拖入 Wallpaper Engine",
    }


def export_static_image(ship: str, bundle: str, name: str | None = None) -> dict:
    """把静态立绘原图导出为普通图片到 resources/exports/ 并打开文件夹。"""
    skin = resolve_skin(ship, bundle, name)
    if not skin:
        return {"ok": False, "error": f"皮肤不存在: {ship}/{bundle}"}
    if skin.get("type") != "static":
        return {"ok": False, "error": "仅静态立绘支持导出图片"}
    asset = local_skin_asset(ship, bundle, name)
    if not asset:
        return {"ok": False, "error": "该皮肤尚未下载，请先下载"}
    src = ROOT / "resources" / asset["dir"] / asset.get("image", "painting.png")
    if not src.exists():
        return {"ok": False, "error": f"未找到立绘文件: {src}"}
    out_dir = ROOT / "resources" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "".join(ch for ch in f"{ship}_{skin.get('name', '')}" if ch not in '<>:"/\\|?*').rstrip(" .")
    dest = out_dir / f"{name or 'painting'}.png"
    shutil.copy2(src, dest)
    try:
        os.startfile(str(out_dir))  # noqa: S606
        opened = True
    except Exception:  # noqa: BLE001
        opened = False
    return {
        "ok": True,
        "path": str(dest),
        "opened": opened,
        "message": f"图片已导出：{dest.name}",
    }


def export_image_data(
    ship: str, bundle: str, name: str | None, data_url: str, index: int | None = None
) -> dict:
    """把前端截取的当前预览帧（PNG dataURL，spine/live2d）保存为图片并打开文件夹。

    index 为动画序号（spine 导出时传入）：文件名用"角色名-序号"（如 企业-3.png），
    便于按动画归档截图；不传时保持"角色名_皮肤名.png"的旧命名。
    """
    import base64

    if not data_url or "," not in data_url:
        return {"ok": False, "error": "缺少图像数据"}
    try:
        png = base64.b64decode(data_url.split(",", 1)[1])
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "图像数据解析失败"}
    if not png.startswith(b"\x89PNG"):
        return {"ok": False, "error": "仅支持 PNG 截图"}
    out_dir = ROOT / "resources" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    if index:
        safe_ship = "".join(ch for ch in ship if ch not in '<>:"/\\|?*').rstrip(" .")
        clean = f"{safe_ship or 'ship'}-{int(index)}"
    else:
        clean = "".join(ch for ch in f"{ship}_{name or bundle}" if ch not in '<>:"/\\|?*').rstrip(" .")
    dest = out_dir / f"{clean or 'capture'}.png"
    dest.write_bytes(png)
    try:
        os.startfile(str(out_dir))  # noqa: S606
        opened = True
    except Exception:  # noqa: BLE001
        opened = False
    return {"ok": True, "path": str(dest), "opened": opened, "message": f"图片已导出：{dest.name}"}


def apply_skin(ship: str, bundle: str, name: str | None, options: dict) -> dict:
    """导出并直接应用到 Wallpaper Engine（新副本 + openWallpaper，绕开编辑器导入路径）。"""
    try:
        proj = _export_project(ship, bundle, name, options)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    ok = apply_wallpaper(Path(proj))
    if not ok:
        return {
            "ok": False,
            "project": proj,
            "error": "应用失败：未找到 Wallpaper Engine 安装目录",
        }
    return {
        "ok": True,
        "project": proj,
        "message": "已生成并应用壁纸，可在 Wallpaper Engine 中查看",
    }


def download_skin(skin: dict, cancel_event: threading.Event | None = None) -> dict:
    """从官方 CDN 下载皮肤 → 提取 → 重建索引 → 刷新资源库。"""
    if skin["type"] not in ("spine", "live2d", "static"):
        return {
            "ok": False,
            "error": f"未知皮肤类型：{skin['type']}",
        }
    def cancelled() -> dict:
        return {
            "ok": False,
            "cancelled": True,
            "skin": skin,
            "downloaded": downloaded,
            "error": "下载已取消",
        }
    stype = skin["type"]
    bundles_dir = ROOT / "resources" / "bundles"
    extracted_dir = ROOT / "resources" / "extracted"
    paintings = skin.get("parts") or [skin["painting"]]
    downloaded = []
    info = cdn.handshake("CN")

    for painting in paintings:
        painting = painting.lower()
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        _emit_stage("正在下载立绘", detail=painting)
        if stype == "static":
            csv = cdn.fetch_hash_csv(info.cdn, info.raw_strings["paintinghash"])
            wanted = {f"painting/{painting}", f"painting/{painting}_tex"}
            targets = [
                (r[0], int(r[1]), r[2])
                for r in (l.split(",") for l in csv.splitlines() if l.strip())
                if len(r) >= 3 and r[0].lower() in wanted
            ]
        elif stype == "live2d":
            csv = cdn.fetch_hash_csv(info.cdn, info.raw_strings["l2dhash"])
            targets = [
                (r[0], int(r[1]), r[2])
                for r in (l.split(",") for l in csv.splitlines() if l.strip())
                if len(r) >= 3 and r[0].lower() == f"live2d/{painting}"
            ]
        else:
            csv = cdn.fetch_hash_csv(info.cdn, info.raw_strings["azhash"])
            wanted = {f"spinepainting/{painting}", f"spinepainting/{painting}_res"}
            targets = [
                (r[0], int(r[1]), r[2])
                for r in (l.split(",") for l in csv.splitlines() if l.strip())
                if len(r) >= 3 and r[0].lower() in wanted
            ]

        for path, size, md5 in targets:
            dest = bundles_dir / path
            _emit_stage("正在下载", detail=path)
            ok = cdn.download_asset(info.cdn, md5, dest, size, cancel_event=cancel_event)
            downloaded.append({"path": path, "ok": ok})

        if cancel_event is not None and cancel_event.is_set():
            return cancelled()

        # 提取
        if stype == "spine":
            _emit_stage("正在提取 Spine 骨架", detail=painting)
            res_bundle = bundles_dir / "spinepainting" / f"{painting}_res"
            main_bundle = bundles_dir / "spinepainting" / painting
            # 大多数皮肤资源在 _res 包里；2B/A2 等新皮肤没有 _res，资源直接在主包里
            src = res_bundle if res_bundle.exists() else main_bundle
            if src.exists():
                registry.get("extractors", "spine").extract(
                    str(src), str(extracted_dir / "spine" / painting)
                )
        elif stype == "live2d":
            _emit_stage("正在提取 Live2D 模型", detail=painting)
            bundle = bundles_dir / "live2d" / painting
            if bundle.exists():
                registry.get("extractors", "live2d").extract(
                    str(bundle), str(extracted_dir / "live2d" / painting)
                )
        else:
            prefab = bundles_dir / "painting" / painting
            tex = bundles_dir / "painting" / f"{painting}_tex"
            # 确保 dependencies 依赖包存在，并下载该立绘的依赖 tex。
            # 并发下载时多个线程会同时抢写 dependencies / 依赖 tex，必须整体串行化。
            with _DEPS_LOCK:
                # dependencies 依赖包会随新皮肤更新，必须按 md5 校验：
                # 本地缺失或与服务器版本不一致时重新下载，否则新皮肤在依赖表里找不到
                # 自己的贴图清单，azur-paint 会 KeyError 并静默降级成简单拼接（立绘错位）。
                dep_path = bundles_dir / "dependencies"
                try:
                    az = cdn.fetch_hash_csv(info.cdn, info.raw_strings["azhash"])
                    row = next(
                        (r for r in (l.split(",") for l in az.splitlines() if l.strip())
                         if len(r) >= 3 and r[0] == "dependencies"),
                        None,
                    )
                    if row:
                        dep_md5 = row[2]
                        stale = (
                            not dep_path.exists()
                            or hashlib.md5(dep_path.read_bytes()).hexdigest() != dep_md5
                        )
                        if stale:
                            logger.info(
                                "dependencies 依赖包已更新（%s -> %s），重新下载",
                                hashlib.md5(dep_path.read_bytes()).hexdigest()[:8] if dep_path.exists() else "缺失",
                                dep_md5[:8],
                            )
                            cdn.download_asset(
                                info.cdn, dep_md5, dep_path,
                                int(row[1]), cancel_event=cancel_event,
                            )
                except Exception as e:  # noqa: BLE001
                    logger.exception("dependencies 刷新失败")
                    print("[static] dependencies 刷新失败:", e)
                # 下载该立绘的全部依赖 tex 包（多层立绘需要）
                try:
                    from plugins.extractors.static import get_dependencies

                    depmap = get_dependencies(str(bundles_dir / "dependencies"))
                    dep_files = [
                        d for d in depmap.get(f"painting/{painting}", [])
                        if d.startswith("painting/") and d != f"painting/{painting}_tex"
                    ]
                    for df in dep_files:
                        dest = bundles_dir / df
                        if dest.exists():
                            continue
                        row = next(
                            (r for r in (l.split(",") for l in csv.splitlines() if l.strip())
                             if len(r) >= 3 and r[0].lower() == df.lower()),
                            None,
                        )
                        if row:
                            cdn.download_asset(
                                info.cdn, row[2], dest, int(row[1]), cancel_event=cancel_event,
                            )
                except Exception as e:  # noqa: BLE001
                    print("[static] 依赖下载失败:", e)
            # 主路径 azur-paint 会自动扫描 bundles 下该立绘的全部贴图，
            # 贴图可能命名为 {painting}_tex 或 {painting}_1_tex/_2_tex（多贴图皮肤），
            # 只要 prefab 存在即可尝试提取，不能用固定的 _tex 存在性作为门槛。
            if prefab.exists():
                _emit_stage("正在合成静态立绘", detail=painting)
                tex_use = next(
                    (t for t in [tex, *sorted(bundles_dir.glob(f"painting/{painting}_*_tex"))] if t.exists()),
                    tex,
                )
                try:
                    registry.get("extractors", "static").extract(
                        str(prefab), str(tex_use), str(extracted_dir / "static" / painting),
                        dependencies_path=str(bundles_dir / "dependencies"),
                        root=ROOT,
                    )
                except Exception as e:  # noqa: BLE001
                    # 提取失败不整单判失败：bundle 已下载，用户可重试提取；
                    # 抛异常会导致已下载文件也被算作下载失败。
                    print(f"[download] {painting} 静态提取失败: {e}")

    if cancel_event is not None and cancel_event.is_set():
        return cancelled()

    # 语音联动：仅 Live2D 皮肤下载语音（互动语音是 L2D 专属设计；
    # Spine / 静态立绘不下载，避免额外耗时）。设置关闭时也不下载。
    if config.get("voice_download") and stype == "live2d":
        try:
            from core import voice as voice_mod
            ship_id = voice_mod.ship_id_for(skin.get("painting", ""))
            if ship_id:
                _emit_stage("正在下载语音", detail=f"船 {ship_id}")
                voice_mod.download_voice(
                    ship_id, info=info, cancel_event=cancel_event,
                    emit=lambda s, d="": _emit_stage(s, detail=d),
                )
        except Exception as e:  # noqa: BLE001
            print(f"[voice] 语音下载失败: {e}")

    # 重建本地索引并刷新资源库
    _emit_stage("正在同步本地索引")
    with _INDEX_LOCK:
        run_tool("build_local_index", timeout=120)
        metadata.reload()
        refresh_library()
    ok_items = [d for d in downloaded if d["ok"]]
    failed_items = [d for d in downloaded if not d["ok"]]
    if not downloaded:
        return {
            "ok": False,
            "skin": skin,
            "downloaded": downloaded,
            "error": "CDN 清单中未找到资源: " + ", ".join(paintings),
        }
    result: dict = {"ok": not failed_items, "skin": skin, "downloaded": downloaded}
    if failed_items:
        result["error"] = f"部分资源下载失败: {len(failed_items)} 个"
    return result


def voice_status(painting: str) -> dict:
    """查询某皮肤对应船的语音状态：shipId、是否已下载、cue 列表。

    pick 按换装序号取该皮肤专属语音（{base}_{N}），L2D 互动 _ex1100 兜底，
    避免「同一角色不同皮肤播同一句」。
    """
    try:
        from core import voice as voice_mod
        ship_id = voice_mod.ship_id_for(painting)
        if not ship_id:
            return {"ok": True, "shipId": None, "has": False, "cues": []}
        cues = voice_mod.voice_cues(ship_id)
        return {
            "ok": True,
            "shipId": ship_id,
            "has": bool(cues),
            "cues": cues,
            "pick": {
                b: voice_mod.pick_cue(ship_id, b, painting=painting)
                for b in ("touch_head", "touch_1", "touch_2", "login", "home")
            },
            "words": voice_mod.words_for(painting),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120], "has": False, "cues": []}


def voice_clean(all_: bool = False) -> dict:
    """清理已下载语音。默认只清「没有已下载 Live2D 皮肤」的船的语音（L2D 专属设计，
    Spine/静态已不下载语音，孤儿语音属于浪费）；all=True 时全部删除。"""
    from core import voice as voice_mod
    if all_:
        return {"ok": True, **voice_mod.clean_voice()}
    try:
        downloaded = downloaded_with_painting()
    except Exception:  # noqa: BLE001
        downloaded = []
    keep: set[int] = set()
    for s in downloaded:
        if s.get("type") == "live2d":
            gid = voice_mod.ship_id_for(s.get("painting", ""))
            if gid:
                keep.add(gid)
    return {"ok": True, **voice_mod.clean_voice(keep)}


def voice_backfill() -> dict:
    """为已下载的 Live2D 皮肤补下语音（按船去重，缺哪个下哪个）。"""
    from core import voice as voice_mod
    try:
        downloaded = downloaded_with_painting()
    except Exception:  # noqa: BLE001
        downloaded = []
    ship_ids: list[int] = []
    seen: set[int] = set()
    for s in downloaded:
        if s.get("type") != "live2d":
            continue
        gid = voice_mod.ship_id_for(s.get("painting", ""))
        if gid and gid not in seen:
            seen.add(gid)
            ship_ids.append(gid)
    if not ship_ids:
        return {"ok": True, "downloaded": 0, "skipped": 0, "ships": []}
    info = cdn.handshake("CN")
    ok_ships, skipped = [], 0
    total = len(ship_ids)
    for i, gid in enumerate(ship_ids, 1):
        if voice_mod.voice_cues(gid):
            skipped += 1
            continue
        _emit_stage("正在下载语音", detail=f"船 {gid}", progress=f"{i}/{total}")
        if voice_mod.download_voice(gid, info=info, emit=lambda s, d="": _emit_stage(s, detail=d)):
            ok_ships.append(gid)
    return {"ok": True, "downloaded": len(ok_ships), "skipped": skipped, "ships": ok_ships}


def open_wallpapers_dir() -> dict:
    """打开软件自己的壁纸输出目录（resources/wallpapers，存放导出的待用壁纸项目）。"""
    d = ROOT / "resources" / "wallpapers"
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(str(d))  # noqa: S606
    return {"ok": True, "path": str(d)}


def clean_exports() -> dict:
    """清理导出的壁纸项目与截图（resources/wallpapers + resources/exports）。"""
    removed = []
    for sub in ("wallpapers", "exports"):
        d = ROOT / "resources" / sub
        if d.is_dir():
            for child in d.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))
    return {"ok": True, "removed": len(removed)}


class Handler(BaseHTTPRequestHandler):
    def _query(self, key: str, default: str = "") -> str:
        """解析查询串 ?key=value。"""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        for part in qs.split("&"):
            k, _, v = part.partition("=")
            if k == key:
                return v
        return default

    def _send(self, status: int, payload: dict) -> None:
        # 诊断日志：记录前端每次 API 调用的请求与响应（真实窗口排障用）
        try:
            print(
                f"[api] {self.command} {self.path} -> {status} "
                f"{json.dumps(payload, ensure_ascii=False)[:300]}",
                flush=True,
            )
        except Exception:  # noqa: BLE001
            pass
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self) -> None:
        """SSE 长连接：把下载/提取/同步等阶段事件推送给前端。"""
        q: queue.Queue = queue.Queue(maxsize=200)
        with _EVENT_LOCK:
            _EVENT_QUEUES.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=30)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # 心跳保活
                    self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _EVENT_LOCK:
                if q in _EVENT_QUEUES:
                    _EVENT_QUEUES.remove(q)

    def _is_local_request(self) -> bool:
        """只允许本机页面调用后端：Host 必须为本机地址，且 Origin（浏览器跨站请求必带）
        若存在也必须是本机。这样即使网页被浏览器打开的其他恶意网站请求，也会被拒绝，
        避免恶意网页借本机 API 删除下载/触发下载占满磁盘。"""
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return False
        origin = self.headers.get("Origin") or ""
        if not origin:
            return True  # 同源请求 / 非浏览器客户端（curl、pywebview 等）
        from urllib.parse import urlparse

        return (urlparse(origin).hostname or "").lower() in ("127.0.0.1", "localhost", "::1")

    def _guard_local(self) -> bool:
        """非本机请求时直接返回 403，返回 False 表示调用方应停止处理。"""
        if self._is_local_request():
            return True
        self._send(403, {"ok": False, "error": "forbidden: 仅允许本机调用"})
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._guard_local():
            return
        self._send(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard_local():
            return
        try:
            ensure_fresh_metadata()
            if self.path.startswith("/api/events"):
                self._stream_events()
                return
            if self.path.startswith("/api/health"):            self._send(200, {"ok": True, "plugins": registry.summary()})
            elif self.path.startswith("/api/library/downloaded"):
                self._send(200, {"ok": True, "skins": downloaded_with_painting()})
            elif self.path.startswith("/api/voice/status"):
                self._send(200, voice_status(self._query("painting", "")))
            elif self.path.startswith("/api/config"):
                self._send(200, get_config())
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception:  # noqa: BLE001
            logger.exception("GET %s failed", self.path)
            try:
                self._send(500, {"ok": False, "error": "internal error"})
            except Exception:  # noqa: BLE001
                pass

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard_local():
            return
        try:
            ensure_fresh_metadata()
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            if self.path.startswith("/api/"):
                print(
                    f"[api] POST {self.path} body={json.dumps(data, ensure_ascii=False)[:200]}",
                    flush=True,
                )
            if self.path.startswith("/api/download/cancel"):
                cancel_download(data.get("download_id") or "")
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/download"):
                ship = data.get("ship")
                bundle = data.get("bundle")
                name = data.get("name")
                download_id = data.get("download_id") or ""
                skin = resolve_skin(ship, bundle, name)
                if not skin:
                    self._send(404, {"ok": False, "error": f"皮肤不存在: {ship}/{bundle}"})
                    return
                cancel_event = _register_cancel(download_id) if download_id else None
                try:
                    result = download_skin(skin, cancel_event)
                finally:
                    if download_id:
                        _unregister_cancel(download_id)
                self._send(200, result)
            elif self.path.startswith("/api/library/delete"):
                self._send(
                    200,
                    delete_skin_files(
                        data.get("ship"), data.get("bundle"), data.get("name")
                    ),
                )
            elif self.path.startswith("/api/library/clear"):
                self._send(200, clear_all_downloads())
            elif self.path.startswith("/api/metadata/update"):
                self._send(200, run_metadata_update())
            elif self.path.startswith("/api/metadata/sync-wiki"):
                self._send(200, run_wiki_sync())
            elif self.path.startswith("/api/config"):
                self._send(200, set_config(data.get("config") or {}))
            elif self.path.startswith("/api/voice/backfill"):
                self._send(200, voice_backfill())
            elif self.path.startswith("/api/voice/clean"):
                self._send(200, voice_clean(all_=bool(data.get("all"))))
            elif self.path.startswith("/api/log"):
                # 前端运行时错误上报（排障用）：打印到 stdout，不落盘
                print(f"[fe-error] {json.dumps(data, ensure_ascii=False)[:800]}", flush=True)
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/export-image-data"):
                self._send(
                    200,
                    export_image_data(
                        data.get("ship"),
                        data.get("bundle"),
                        data.get("name"),
                        data.get("dataUrl") or "",
                        index=data.get("index"),
                    ),
                )
            elif self.path.startswith("/api/export-image"):
                self._send(
                    200,
                    export_static_image(data.get("ship"), data.get("bundle"), data.get("name")),
                )
            elif self.path.startswith("/api/export"):
                self._send(
                    200,
                    export_skin(
                        data.get("ship"),
                        data.get("bundle"),
                        data.get("name"),
                        data.get("options") or {},
                    ),
                )
            elif self.path.startswith("/api/apply"):
                self._send(
                    200,
                    apply_skin(
                        data.get("ship"),
                        data.get("bundle"),
                        data.get("name"),
                        data.get("options") or {},
                    ),
                )
            elif self.path.startswith("/api/palette"):
                ship = data.get("ship")
                bundle = data.get("bundle")
                name = data.get("name")
                mode = data.get("mode") or "auto"
                bg_color = data.get("bgColor")
                skin = resolve_skin(ship, bundle, name)
                asset = local_skin_asset(ship, bundle, name)
                if not skin or not asset:
                    self._send(200, {"ok": False, "error": "皮肤不存在或未下载"})
                else:
                    src = find_palette_source({**skin, "asset": asset}, ROOT)
                    palette = extract_palette(src) if src else None
                    css = mode_css(mode, palette, solid_color=bg_color)
                    self._send(
                        200,
                        {
                            "ok": bool(palette),
                            "colors": palette or fallback_palette(),
                            "source": str(src) if src else None,
                            "css": css,
                        },
                    )
            elif self.path.startswith("/api/open/download-dir"):
                os.startfile(str(ROOT / "resources" / "bundles"))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/extracted-dir"):
                os.startfile(str(ROOT / "resources" / "extracted"))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/wallpapers-dir"):
                self._send(200, open_wallpapers_dir())
            elif self.path.startswith("/api/library/clean-exports"):
                self._send(200, clean_exports())
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as e:  # noqa: BLE001
            logger.exception("POST %s failed", self.path)
            self._send(500, {"ok": False, "error": str(e)})

    def log_message(self, *args) -> None:  # noqa: D401
        pass


def main(port: int = 8766) -> None:
    """启动后端 API 服务。

    注意：打包版/桌面版会以线程方式调用 main(8770) 传入端口，
    因此这里**不再**从 sys.argv 读端口（之前会被启动参数意外覆盖，
    导致前端连不上后端）。
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"backend API listening on http://127.0.0.1:{port}")
    logger.info("backend API listening on http://127.0.0.1:%s", port)
    server.serve_forever()


if __name__ == "__main__":
    _port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    main(_port)
