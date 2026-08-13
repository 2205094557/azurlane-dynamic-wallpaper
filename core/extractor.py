"""AssetBundle 解包：提取 Spine（.skel/.atlas/贴图）与 Live2D（moc3 模型）。"""

from __future__ import annotations

from pathlib import Path


def extract_spine(bundle_path: Path, out_dir: Path) -> dict:
    """从 spinepainting bundle 中提取 Spine 三件套。"""
    raise NotImplementedError("M0")


def extract_live2d(bundle_path: Path, out_dir: Path) -> dict:
    """从 live2d bundle 中提取 Cubism 模型（moc3/model3.json/贴图）。"""
    raise NotImplementedError("M0")

