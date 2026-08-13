"""给提取出的 model3.json 补上动作引用（提取器产出的动作在 Animation/ 下但未写入清单）。"""

import json
import shutil
import sys
from pathlib import Path


def patch_model3(model3: Path) -> None:
    data = json.loads(model3.read_text(encoding="utf-8"))
    anim_src = None
    for p in [model3.parent, *model3.parent.parents]:
        cand = p / "Animation"
        if cand.is_dir():
            anim_src = cand
            break
    if anim_src is None:
        print("no Animation dir, skip")
        return
    if "Motions" in data.get("FileReferences", {}):
        print("already patched")
        return
    anim_dir = model3.parent / "Animation"
    if anim_src.resolve() != anim_dir.resolve() and not anim_dir.exists():
        shutil.copytree(anim_src, anim_dir)
    motions: dict[str, list] = {}
    for f in sorted(anim_dir.glob("*.motion3.json")):
        name = f.stem.replace(".motion3", "")
        group = "Idle" if name.startswith("idle") or name in ("normal", "home") else "Tap"
        motions.setdefault(group, []).append(
            {"File": f"Animation/{f.name}", "FadeInTime": 0.5, "FadeOutTime": 0.5}
        )
    if motions:
        data["Motions"] = motions
        # pixi-live2d-display 0.4 读取 FileReferences.Motions（非标准但该库如此）
        data.setdefault("FileReferences", {})["Motions"] = motions
        model3.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("patched groups:", {k: len(v) for k, v in motions.items()})


if __name__ == "__main__":
    patch_model3(Path(sys.argv[1]))
