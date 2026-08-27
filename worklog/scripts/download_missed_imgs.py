#!/usr/bin/env python3
"""Скачиваем фото постов 1316/1314/1311 в максимальном качестве (cs -> max)."""
import json
import os
import re
import subprocess

REPO = '/home/z/my-project/repo-bf'
IMG_DIR = f'{REPO}/public/images'
POST_IDS = ['1316', '1314', '1311']

raw_lines = [l.strip() for l in open('/home/z/my-project/vk_imgs_missed_raw.txt') if l.strip()]
manifest = {}
for pid, line in zip(POST_IDS, raw_lines):
    urls = json.loads(json.loads(line) if line.startswith('"') else line)
    files = []
    for i, src in enumerate(urls, 1):
        # поднимаем разрешение: берём максимальный размер из списка as=
        m = re.search(r'as=([0-9x,]+)', src)
        best_cs = None
        if m:
            sizes = m.group(1).split(',')
            last = sizes[-1]  # максимальный размер в списке
            best_cs = f'cs={last}'
        url = re.sub(r'cs=\d+x\d+', best_cs or 'cs=1280x853', src)
        ext = '.png' if '.png' in url.split('?')[0] else '.jpg'
        fname = f'post-{pid}-{i:02d}{ext}'
        fpath = os.path.join(IMG_DIR, fname)
        subprocess.run(['curl', '-sL', '--max-time', '30', '-o', fpath, url], capture_output=True)
        ok = os.path.exists(fpath) and os.path.getsize(fpath) > 3000
        if not ok and os.path.exists(fpath):
            os.remove(fpath)
        print(pid, i, fname, 'OK' if ok else 'FAIL')
        if ok:
            files.append(fname)
    manifest[pid] = files

json.dump(manifest, open('/home/z/my-project/img_manifest_missed.json', 'w'), ensure_ascii=False, indent=1)
print('manifest:', json.dumps(manifest))
