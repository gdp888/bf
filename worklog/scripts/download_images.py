#!/usr/bin/env python3
"""Скачивает фото постов VK локально в репозиторий."""
import json
import os
import subprocess

BASE = '/home/z/my-project'
REPO = f'{BASE}/repo-bf'
IMG_DIR = f'{REPO}/public/images'
os.makedirs(IMG_DIR, exist_ok=True)

posts = json.load(open(f'{BASE}/vk_posts_full.json', encoding='utf-8'))

manifest = {}
for p in posts:
    pid = p['id']
    urls = p.get('imgs', [])
    files = []
    for i, url in enumerate(urls, 1):
        ext = '.png' if '.png' in url.split('?')[0] else '.jpg'
        fname = f'post-{pid}-{i:02d}{ext}'
        fpath = os.path.join(IMG_DIR, fname)
        # скачиваем только если ещё нет
        if not os.path.exists(fpath):
            r = subprocess.run(['curl', '-sL', '--max-time', '25', '-o', fpath, url],
                               capture_output=True)
            if r.returncode != 0:
                print(f'FAIL {fname}')
                continue
        size = os.path.getsize(fpath)
        if size < 3000:  # мусор/заглушка
            os.remove(fpath)
            print(f'TINY  {fname} ({size}b) skipped')
            continue
        files.append(fname)
        print(f'OK    {fname} {size//1024}Kb')
    if files:
        manifest[pid] = files

json.dump(manifest, open(f'{BASE}/img_manifest.json', 'w'), ensure_ascii=False, indent=1)
print('\nSaved manifest:', len(manifest), 'posts with local images')
