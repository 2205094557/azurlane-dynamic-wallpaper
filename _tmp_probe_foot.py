# -*- coding: utf-8 -*-
"""查阿罗芒什·足尖弓矢的 nagami 配置：painting / hitAreas / 互动类型。"""
import sys, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener.addheaders = [('User-Agent', 'Mozilla/5.0')]

def get_json(u):
    with opener.open(u, timeout=12) as r:
        return json.load(r)

idx = get_json('https://data.nagami.moe/spine/index.json')
# 找名字含足尖弓矢/阿罗芒什的条目
cands = []
for s in idx.get('skins', []):
    txt = json.dumps(s, ensure_ascii=False)
    if '足尖弓矢' in txt or '阿罗芒什' in txt or 'Arromanches' in txt:
        cands.append(s)
        print('index 条目:', s.get('id'), s.get('asset'), '|', s.get('displayName', ''))
for c in cands[:3]:
    asset = c.get('asset')
    print(f'\n=== model {asset}.json ===')
    try:
        m = get_json(f'https://data.nagami.moe/spine/models/{asset}.json')
        print('hitAreas:', [(h.get('name'), h.get('position'), h.get('size')) for h in m.get('hitAreas', [])])
        print('spineVersions:', m.get('spineVersions'))
    except Exception as e:
        print('model 拉取失败:', e)
    sid = c.get('id')
    try:
        cfg = get_json(f'https://data.nagami.moe/spine/skins/{sid}.json')
        cc = ((cfg.get('interaction') or {}).get('drag_data') or {}).get('config_client')
        print('config_client:', json.dumps(cc, ensure_ascii=False) if cc else 'null')
        print('hit_area:', cfg.get('interaction', {}).get('hit_area'))
    except Exception as e:
        print('skin 拉取失败:', e)