# -*- coding: utf-8 -*-
"""无头验证：jishang_3 / geliqiya_3 新动画命名皮肤的互动判定与点击轮换。

进程内导出壁纸项目 → 注入调试片段 → headless Edge dump 结果。
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.registry import Registry  # noqa: E402

CASES = [
    ("jishang_3", "吉尚", "_3", "Milk&Kiss"),
    ("geliqiya_3", "戈里齐亚", "_3", "间谍行动大失败！"),
]

MSEDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# 注入到 </body> 前的调试片段：等骨架就绪后输出判定与点击轮换结果
DEBUG_SNIPPET = """
<script>
(function () {
  var tries = 0;
  var timer = setInterval(function () {
    tries++;
    var ready = window.skeletons && skeletons.length && skeletons[0] && skeletons[0].skeleton && skeletons[0].state;
    if (!ready) { if (tries > 200) { document.title = 'DBGTIMEOUT'; clearInterval(timer); } return; }
    clearInterval(timer);
    var out = { anims: animNames0().join(','), interactive: !!isInteractiveSkin(), clicks: [] };
    try {
      for (var i = 0; i < 3; i++) {
        simulateClick();
        var cur = skeletons[0].state.getCurrent(0);
        out.clicks.push(cur && cur.animation ? cur.animation.name : '(none)');
      }
    } catch (e) { out.error = String(e && e.message || e); }
    out.voice = window.VOICE_JSON ? Object.keys(VOICE_JSON.pick || {}).map(function (k) { return k + '=' + VOICE_JSON.pick[k]; }).join(';') : 'null';
    var node = document.createElement('pre');
    node.id = 'dbg';
    node.textContent = JSON.stringify(out);
    document.body.appendChild(node);
    document.title = 'DBGDONE';
  }, 100);
})();
</script>
"""


def simulate_click_js():
    # 模拟 mousedown 点击画布中心（互动路径入口），复用模板原生处理链
    return """
function simulateClick() {
  var ev = new MouseEvent('mousedown', {
    button: 0, clientX: canvas.clientWidth / 2, clientY: canvas.clientHeight / 2, bubbles: true
  });
  canvas.dispatchEvent(ev);
  window.dispatchEvent(new MouseEvent('mouseup', {}));
}
"""


def export_case(painting, ship, bundle, name):
    locs = json.loads((ROOT / "resources" / "metadata" / "local_skins.json").read_text(encoding="utf-8"))
    hit = next(l for l in locs if l.get("painting") == painting)
    skins = json.loads((ROOT / "resources" / "metadata" / "skins.json").read_text(encoding="utf-8"))
    sk = next(s for s in skins if s.get("painting") == painting)
    exporter = Registry(ROOT / "plugins").discover().get("exporters", "wallpaper_spine")
    proj = exporter.export(
        {**sk, "asset": hit["asset"]},
        {
            "root": str(ROOT), "bg": "monet", "scale": 100,
            "offsetX": 0, "offsetY": 0, "alignment": 0,
            "voice": True, "intro": True, "interact": True, "track": True,
            "showHitAreas": False,
        },
        str(ROOT / "resources" / "wallpapers"),
    )
    return Path(proj)


def main():
    msedge = next((p for p in MSEDGE_CANDIDATES if Path(p).exists()), None)
    if not msedge:
        print("msedge not found")
        return 1
    ok = True
    for painting, ship, bundle, name in CASES:
        proj = export_case(painting, ship, bundle, name)
        html = (proj / "index.html").read_text(encoding="utf-8")
        # 注入 simulateClick + 调试片段
        html = html.replace("</body>", "<script>" + simulate_click_js() + "</script>" + DEBUG_SNIPPET + "</body>")
        dbg = proj / "_debug.html"
        dbg.write_text(html, encoding="utf-8")
        url = "file:///" + str(dbg).replace("\\", "/")
        r = subprocess.run(
            [msedge, "--headless", "--disable-gpu", "--allow-file-access-from-files",
             "--dump-dom", "--virtual-time-budget=15000", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        m = re.search(r'<pre id="dbg">(.*?)</pre>', r.stdout, re.S)
        if not m:
            print(f"[FAIL] {painting}: 无调试输出")
            ok = False
        else:
            import html as html_mod
            out = json.loads(html_mod.unescape(m.group(1)))
            interactive = out.get("interactive")
            clicks = out.get("clicks") or []
            anims = out.get("anims", "")
            hasVoice = out.get("voice", "null") != "null" and out.get("voice", "")
            played = [c for c in clicks if c not in ("normal", "(none)")]
            good = interactive and played
            print(f"[{'PASS' if good else 'FAIL'}] {painting}")
            print("   anims:", anims[:120])
            print("   interactive:", interactive, " voice:", hasVoice[:120])
            print("   3 次点击播放:", clicks)
            if not good:
                ok = False
        dbg.unlink(missing_ok=True)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
