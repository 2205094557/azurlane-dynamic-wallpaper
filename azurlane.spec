# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir，包含代码 + 模板 + 元数据 + 头像 + 前端 dist。"""
from PyInstaller.utils.hooks import collect_all

import os


def _walk_files(src, dest_prefix, skip=()):
    out = []
    for root, _dirs, files in os.walk(src):
        for f in files:
            if f in skip:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(root, src)
            out.append((full, os.path.join(dest_prefix, rel)))
    return out


datas = [
    ("templates", "templates"),
    ("resources/avatars", "resources/avatars"),
    ("frontend/dist", "frontend/dist"),
    ("tools", "tools"),
    ("core", "core"),
    # plugins 目录必须作为文件打包：注册表按目录扫描发现插件
    ("plugins", "plugins"),
    # 提取器运行时依赖的参考实现：UnityPyLive2DExtractor（L2D 完整转换）与 azur-paint（静态合成）
    (
        "references/UnityPyLive2DExtractor/UnityPyLive2DExtractor",
        "references/UnityPyLive2DExtractor/UnityPyLive2DExtractor",
    ),
    ("references/azur-paint/main.py", "references/azur-paint"),
    ("references/azur-paint/main2.py", "references/azur-paint"),
]
# 元数据：排除 local_skins.json（本地下载索引，打包版从空状态开始）
datas += _walk_files("resources/metadata", "resources/metadata", skip={"local_skins.json"})

u_datas, u_bins, u_hidden = collect_all("UnityPy")
p_datas, p_bins, p_hidden = collect_all("pypinyin")
f_datas, f_bins, f_hidden = collect_all("fmod_toolkit")
pyf_datas, pyf_bins, pyf_hidden = collect_all("pyfmodex")
arch_datas, arch_bins, arch_hidden = collect_all("archspec")
cl_datas, cl_bins, cl_hidden = collect_all("coloredlogs")
hf_datas, hf_bins, hf_hidden = collect_all("humanfriendly")
datas += u_datas + p_datas + f_datas + pyf_datas + arch_datas + cl_datas + hf_datas
binaries = u_bins + p_bins + f_bins + pyf_bins + arch_bins + cl_bins + hf_bins

hiddenimports = (
    [
        "core.registry",
        "core.metadata",
        "core.library",
        "core.palette",
        "core.we_integration",
        "core.events",
        "core.wallpaper",
        "plugins.sources.cdn",
        "plugins.sources.cdn_proto.p10min_pb_pb2",
        "plugins.sources.local",
        "plugins.extractors.spine",
        "plugins.extractors.live2d",
        "plugins.extractors.static",
        # UnityPyLive2DExtractor 进程内运行所需
        "coloredlogs",
        "humanfriendly",
        "sssekai",
        "sssekai.fmt.motion3",
        "sssekai.fmt.moc3",
        "sssekai.unity",
        "sssekai.unity.AnimationClip",
        "plugins.exporters.wallpaper_spine",
        "plugins.exporters.wallpaper_live2d",
        "plugins.exporters.wallpaper_static",
        "requests",
        "PIL",
        "google.protobuf",
    ]
    + u_hidden
    + p_hidden
    + f_hidden
    + pyf_hidden
    + arch_hidden
    + cl_hidden
    + hf_hidden
)

a = Analysis(
    ["app_pack.py"],
    pathex=["D:/download/codex/azurlane-dynamic-wallpaper"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="azurlane-wallpaper",
    icon=os.path.join(SPECPATH, "resources", "icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="azurlane-wallpaper",
)
