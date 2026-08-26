# -*- coding: utf-8 -*-
"""PreviewView.vue：删 animMulti 状态/重置/导出参数。"""
import re, sys, subprocess
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
p = r'D:\codex\azurlane-dynamic-wallpaper\frontend\src\features\preview\PreviewView.vue'
s = open(p, encoding='utf-8').read()

# 1) 状态定义：删 animMulti 行（带注释行）
s = s.replace('const animMulti = ref([])\n', '')
print('1) animMulti 状态删除')

# 2) 重置处
s = s.replace('''    animMulti.value = []
''', '')
print('2) animMulti 重置删除')

# 3) 导出参数（两处 animation/animations）
old3 = '''      animation: animation.value,
      animations: exportAnimations(),
'''
n = s.count(old3)
s = s.replace(old3, '')
print('3) animation/animations 参数删除:', n, '处')

open(p, 'w', encoding='utf-8').write(s)
js = re.search(r'<script setup>(.*?)</script>', s, re.S).group(1)
open(r'C:/Windows/Temp/_pv.js', 'w', encoding='utf-8').write(js)
r = subprocess.run(['node', '--check', 'C:/Windows/Temp/_pv.js'], capture_output=True, text=True)
print('语法:', 'OK' if r.returncode == 0 else 'ERR ' + r.stderr[:400])