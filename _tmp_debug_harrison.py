# -*- coding: utf-8 -*-
"""调试：哈里森在 wiki 船表 / extras / merge 里的皮肤名对齐。"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\codex\azurlane-dynamic-wallpaper\tools')
import importlib.util

spec = importlib.util.spec_from_file_location('swc', r'D:\codex\azurlane-dynamic-wallpaper\tools\sync_wiki_catalog.py')
swc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(swc)

raw = swc.fetch_wiki_catalog()
wmap = swc.build_wiki_ships(raw)
for key, w in wmap.items():
    if '哈里' in (w.get('name') or ''):
        print('WIKI key=', key)
        print('WIKI name=', w.get('name'), 'skins=', [(s.get('name'), s.get('order')) for s in w.get('skins', [])])

extras = json.load(open(r'D:\codex\azurlane-dynamic-wallpaper\resources\metadata\wiki_extra_ships.json', encoding='utf-8'))
for e in extras:
    if '哈里' in (e.get('name') or ''):
        print('EXTRA name=', e.get('name'))
        print('EXTRA skins=', [(s.get('painting'), s.get('bundle'), s.get('name')) for s in e.get('skins', [])])