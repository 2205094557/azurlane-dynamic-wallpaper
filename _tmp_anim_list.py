# -*- coding: utf-8 -*-
"""列出阿罗芒什足尖弓矢 skel 的动画名。"""
import sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

painting = 'aluomangshi_2'
import base64, os, re

# 从本地资源找
root = r'D:\codex\azurlane-dynamic-wallpaper\resources\extracted\spine'
cands = [d for d in os.listdir(root) if 'aluomang' in d or 'a2' == d or 'a2_2' == d]
print('候选目录:', cands)
for d in cands:
    skel = os.path.join(root, d, d + '.skel')
    if os.path.exists(skel):
        data = open(skel, 'rb').read()
        # 提取动画名字符串（ASCII 可读串）
        names = sorted(set(re.findall(rb'[A-Za-z][A-Za-z0-9_]{1,20}', data)))
        # 过滤像动画名的（全小写开头带下划线数字）
        anims = [n.decode() for n in names if re.fullmatch(rb'[a-z][a-z0-9_]*', n) and ('drag' in n.decode() or 'ex' in n.decode() or 'normal' in n.decode() or 'expression' in n.decode() or re.search(rb'\d$', n))]
        print(f'{d}: 候选动画 {sorted(set(anims))}')
        # 也可以输出全部含 drag/ex 的
        print(f'{d}: 全部含drag/ex: {[n.decode() for n in names if b"drag" in n or b"ex" in n]}')