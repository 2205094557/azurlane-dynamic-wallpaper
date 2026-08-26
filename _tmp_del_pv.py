# -*- coding: utf-8 -*-
"""PreviewView.vue：删除动画切换相关（animMulti/stepAnim/animIndex/exportAnimations/onKeydown 动画分支）。"""
import re, sys, subprocess
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
p = r'D:\codex\azurlane-dynamic-wallpaper\frontend\src\features\preview\PreviewView.vue'
s = open(p, encoding='utf-8').read()

# 1) onSpineAnims 去掉 animMulti 行
s = s.replace('''  if (!animMulti.value.length && animation.value) animMulti.value = [animation.value]
''', '')
print('1) onSpineAnims animMulti 行删除')

# 2) 删 animIndex + stepAnim + exportAnimations 整块
old2 = '''const animIndex = computed(() => {
  const i = animOptions.value.findIndex((o) => o.value === animation.value)
  return i >= 0 ? i : 0
})

function stepAnim(dir) {
  const n = animOptions.value.length
  if (!n) return
  const next = (animIndex.value + dir + n) % n
  animation.value = animOptions.value[next].value
}

function exportAnimations() {
  const list = [...(animMulti.value || [])]
  if (animation.value && !list.includes(animation.value)) list.unshift(animation.value)
  return list
}

'''
assert old2 in s, 'block2 未匹配'
s = s.replace(old2, '')
print('2) animIndex/stepAnim/exportAnimations 删除')

# 3) onKeydown 里的动画切换
old3 = '''  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  if (animOptions.value.length) {
    e.preventDefault()
    stepAnim(e.key === 'ArrowLeft' ? -1 : 1)
  }
}'''
new3 = '''  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
}'''
assert old3 in s, 'block3 未匹配'
s = s.replace(old3, new3, 1)
print('3) onKeydown 动画分支删除')

open(p, 'w', encoding='utf-8').write(s)
print('写入完成')

js = re.search(r'<script setup>(.*?)</script>', s, re.S).group(1)
open(r'C:/Windows/Temp/_pv.js', 'w', encoding='utf-8').write(js)
r = subprocess.run(['node', '--check', 'C:/Windows/Temp/_pv.js'], capture_output=True, text=True)
print('语法:', 'OK' if r.returncode == 0 else 'ERR ' + r.stderr[:400])