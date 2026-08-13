"""Wallpaper Engine 集成：定位安装目录、应用壁纸、打开编辑器。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

COMMON_PATHS = [
    Path("C:/Program Files (x86)/Steam/steamapps/common/wallpaper_engine"),
    Path("C:/Program Files/Steam/steamapps/common/wallpaper_engine"),
    Path("D:/Program Files/Steam/steamapps/common/wallpaper_engine"),
    Path("D:/Program Files (x86)/Steam/steamapps/common/wallpaper_engine"),
    Path("E:/Steam/steamapps/common/wallpaper_engine"),
]


def _steam_path_from_registry() -> Path | None:
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
        ):
            with winreg.OpenKey(hive, key) as k:
                val, _ = winreg.QueryValueEx(k, "SteamPath")
                p = Path(val) / "steamapps" / "common" / "wallpaper_engine"
                if (p / "wallpaper64.exe").exists():
                    return p
    except Exception:  # noqa: BLE001
        pass
    return None


def find_wallpaper_engine_dir() -> Path | None:
    p = _steam_path_from_registry()
    if p:
        return p
    for cand in COMMON_PATHS:
        if (cand / "wallpaper64.exe").exists():
            return cand
    return None


def _run(exe: str, args: list[str]) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([exe, *args], creationflags=creationflags)


def _ascii_copy_name(project_name: str) -> str:
    """WE 的 openWallpaper IPC 会把中文路径以乱码写进 config.json（selectedwallpapers），
    重启后壁纸将无法加载。副本目录名只保留 ASCII 字符，标题仍由 project.json 提供。"""
    ascii_part = re.sub(r"[^A-Za-z0-9_-]", "", project_name)[:32].strip("_-")
    return f"{ascii_part or 'azl2d'}_{uuid.uuid4().hex[:8]}"


def apply_wallpaper(project_dir: Path) -> bool:
    we = find_wallpaper_engine_dir()
    if not we:
        return False
    name = _ascii_copy_name(project_dir.name)
    dest = we / "projects" / "myprojects" / name
    shutil.copytree(project_dir, dest)
    index = dest / "index.html"
    if not index.exists():
        return False
    _run(str(we / "wallpaper64.exe"), ["-control", "openWallpaper", "-file", str(index)])
    return True


def open_editor(project_dir: Path) -> bool:
    we = find_wallpaper_engine_dir()
    if not we:
        return False
    pj = project_dir / "project.json"
    if not pj.exists():
        return False
    _run(str(we / "wallpaper64.exe"), ["-window", "editor", "-project", str(pj)])
    return True
