# -*- coding: utf-8 -*-
"""删除 wall_spine.html 的 animselect / ANIM_OPTIONS / animNameFromValue。"""
import re, sys, subprocess
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

p = r'D:\codex\azurlane-dynamic-wallpaper\templates\wallpaper_spine.html'
s = open(p, encoding='utf-8').read()
orig = len(s)

# 1) 删除 ANIM_OPTIONS 变量行
s2 = s.replace('var ANIM_OPTIONS = {{ANIM_OPTIONS}}; // 可在 WE 下拉切换的动画列表\n', '')
print('1) ANIM_OPTIONS 行删除:', len(s) != len(s2))

# 2) 删除 animNameFromValue 函数（L155-162 附近整块）
i = s2.find('function animNameFromValue(')
if i >= 0:
    j = s2.find('}', s2.find('{', i))  # 找函数结束
    # 找函数结束（大括号配对）
    depth = 0; k = i
    while k < len(s2):
        if s2[k] == '{': depth += 1
        elif s2[k] == '}':
            depth -= 1
            if depth == 0: break
        k += 1
    block = s2[i:k+1]
    # 含注释行（如果紧邻）
    pre = s2[max(0, i-120):i]
    m = re.search(r'//[^\n]*\n[^\n]*$', pre)
    start = i
    if m:
        s2_pre = s2[:i]
        nl = s2_pre.rfind('\n', 0, i-1)
        line_pre = s2_pre[nl+1:i]
        if line_pre.strip().startswith('//'):
            start = nl+1
    s2 = s2[:start] + s2[k+1:]
    print('2) animNameFromValue 函数删除')

# 3) 首推里的 animselect 处理
s2 = s2.replace('''        var firstName = properties.animselect ? animNameFromValue(properties.animselect.value) : null;
        if (firstName) playAnim(firstName);
''', '')
print('3) 首推 animselect 删除')

# 4) 监听里的 animselect 处理
s2 = s2.replace('''      if (properties.animselect) {
        var animName = animNameFromValue(properties.animselect.value);
        if (animName) playAnim(animName);
      }
''', '')
print('4) 监听 animselect 删除')

open(p, 'w', encoding='utf-8').write(s2)
print('文件大小:', orig, '->', len(s2))

js = re.search(r'<script[^>]*>(.*?)</script>', s2, re.S).group(1)
js = re.sub(r'\{\{[A-Z_]+(?:_JSON)?\}\}', 'null', js)
open(r'C:/Windows/Temp/_t.js', 'w', encoding='utf-8').write(js)
r = subprocess.run(['node', '--check', 'C:/Windows/Temp/_t.js'], capture_output=True, text=True)
print('语法:', 'OK' if r.returncode == 0 else 'ERR ' + r.stderr[:400])