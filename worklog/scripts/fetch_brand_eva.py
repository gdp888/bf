#!/usr/bin/env python3
"""Парсим фирменную обложку + логотип группы ВК и фото из поста Евы (1319)."""
import json
import sys
import time

sys.path.insert(0, '/home/z/my-project/scripts')
from ab import ab, ab_eval  # noqa: E402

OUT = '/home/z/my-project/brand_eva.json'
result = {}

# ---------- 1. Главная группы: обложка + аватар ----------
ab(['open', 'https://vk.ru/dostigenie_deti'])
ab(['wait', '--load', 'networkidle'])
time.sleep(3)

js_page = """
(() => {
  const og = document.querySelector('meta[property="og:image"]');
  const imgs = [];
  const seen = new Set();
  document.querySelectorAll('img').forEach(im => {
    const src = im.src || '';
    if (!/vkuserphoto|userapi|impg/.test(src)) return;
    const base = src.split('?')[0];
    if (seen.has(base)) return;
    seen.add(base);
    const r = im.getBoundingClientRect();
    imgs.push({
      src, w: im.naturalWidth, h: im.naturalHeight,
      dx: Math.round(r.x), dy: Math.round(r.y),
      dw: Math.round(r.width), dh: Math.round(r.height),
      cls: (im.className || '').toString().slice(0, 80),
      alt: im.alt || ''
    });
  });
  const bgs = [];
  document.querySelectorAll('div, a, span').forEach(el => {
    const st = (el.getAttribute('style') || '');
    const m = st.match(/background-image:\\s*url\\(["']?([^"')]+)["']?\\)/);
    if (!m) return;
    if (!/vkuserphoto|userapi|impg/.test(m[1])) return;
    const r = el.getBoundingClientRect();
    if (r.width < 50 || r.height < 50) return;
    bgs.push({src: m[1], dx: Math.round(r.x), dy: Math.round(r.y),
              dw: Math.round(r.width), dh: Math.round(r.height),
              cls: (el.className || '').toString().slice(0, 80)});
  });
  return JSON.stringify({og: og ? og.content : null, imgs, bgs});
})()"""
raw = ab_eval(js_page)
data = json.loads(raw) if isinstance(raw, str) else raw
result['group_page'] = data
print('GROUP PAGE: og =', (data.get('og') or 'none')[:100])
print('  imgs:', len(data.get('imgs', [])), '| bgs:', len(data.get('bgs', [])))
for im in data.get('imgs', []):
    print(f"   img dy={im['dy']} dw={im['dw']}x{im['dh']} nat={im['w']}x{im['h']} {im['src'][:90]}")
for b in data.get('bgs', []):
    print(f"   bg  dy={b['dy']} dw={b['dw']}x{b['dh']} {b['src'][:90]}")

# ---------- 2. Пост Евы 1319: фото ----------
ab(['open', 'https://vk.ru/wall-223846998_1319'])
ab(['wait', '--load', 'networkidle'])
time.sleep(3)
for _ in range(3):
    ab_eval("""(() => { document.querySelectorAll('img[loading="lazy"]').forEach(im => { im.loading = 'eager'; }); return document.querySelectorAll('img').length; })()""")
    ab(['scroll', 'down', '400']); time.sleep(1)
    ab(['scroll', 'up', '200']); time.sleep(1)

raw = ab_eval(js_page)
data = json.loads(raw) if isinstance(raw, str) else raw
result['post_1319'] = data
print('POST 1319: imgs:', len(data.get('imgs', [])), '| bgs:', len(data.get('bgs', [])))
for im in data.get('imgs', []):
    print(f"   img dw={im['dw']}x{im['dh']} nat={im['w']}x{im['h']} {im['src'][:90]}")

json.dump(result, open(OUT, 'w'), ensure_ascii=False, indent=1)
print('saved ->', OUT)
