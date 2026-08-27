#!/usr/bin/env python3
"""Качаем обложку, логотип и фото Евы в HD (cs -> max из as=)."""
import json
import os
import re
import subprocess

OUT_DIR = '/home/z/my-project/brand_dl'
os.makedirs(OUT_DIR, exist_ok=True)
data = json.load(open('/home/z/my-project/brand_eva.json'))


def hd_url(src):
    """Поднимаем cs= до максимального размера из списка as=."""
    m = re.search(r'as=([0-9x,]+)', src)
    if m:
        sizes = m.group(1).split(',')
        best = sizes[-1]
        return re.sub(r'cs=\d+x\d+', f'cs={best}', src), best
    return src, None


def dl(name, url):
    path = os.path.join(OUT_DIR, name)
    subprocess.run(['curl', '-sL', '--max-time', '40', '-A',
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
                    '-o', path, url], capture_output=True)
    ok = os.path.exists(path) and os.path.getsize(path) > 3000
    size = os.path.getsize(path) if os.path.exists(path) else 0
    print(f'{name}: {"OK" if ok else "FAIL"} {size/1024:.0f}Kb')
    return path if ok else None


# 1. Обложка (bg с главной)
cover_raw = data['group_page']['bgs'][0]['src']
cover_url, sz = hd_url(cover_raw)
print('cover cs upgrade:', sz, cover_url[:110])
dl('fund-cover.jpg', cover_url)

# 2. Логотип: img 96x96 nat 240x240 с главной (Uw6FHYddQ)
logo = None
for im in data['group_page']['imgs']:
    if im['dw'] == 96 and im['nat_w' if False else 'w'] and im['dw'] != 20:
        pass
for im in data['group_page']['imgs']:
    if im['dw'] == 96 and im['h'] == 240:
        logo = im['src']
        break
if not logo:  # фолбэк: аватар из шапки поста (34x34, nat 72)
    for im in data['post_1319']['imgs']:
        if im['dw'] == 34:
            logo = im['src']
            break
logo_url, sz = hd_url(logo)
print('logo cs upgrade:', sz, logo_url[:110])
dl('fund-logo.jpg', logo_url)

# 3. Фото Евы: пост 1319, два портретных 640x853
eva_n = 0
for im in data['post_1319']['imgs']:
    if im['w'] >= 600 and im['h'] >= 700:
        eva_n += 1
        u, sz = hd_url(im['src'])
        print(f'eva-{eva_n} cs upgrade:', sz, u[:110])
        dl(f'eva-1319-{eva_n:02d}.jpg', u)
