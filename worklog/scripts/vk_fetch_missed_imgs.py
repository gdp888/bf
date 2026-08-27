#!/usr/bin/env python3
"""Точечно добираем фото к постам 1316, 1314, 1311 (ленивая загрузка)."""
import json
import subprocess
import time

GROUP_ID = '223846998'
POSTS = ['1316', '1314', '1311']


def ab(cmd, timeout=60):
    r = subprocess.run(['agent-browser'] + cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def ab_eval(js, timeout=60):
    out = ab(['eval', js], timeout)
    if out.startswith('"') and out.endswith('"'):
        out = json.loads(out)
    return out


if __name__ == '__main__':
    out = {}
    for pid in POSTS:
        ab(['open', f'https://vk.ru/wall-{GROUP_ID}_{pid}'])
        ab(['wait', '--load', 'networkidle'])
        time.sleep(2)
        # несколько проходов скролла вверх-вниз, чтобы VK догрузил все картинки
        for _ in range(3):
            ab_eval("""
(() => {
  document.querySelectorAll('img[loading="lazy"]').forEach(im => { im.loading = 'eager'; });
  return document.querySelectorAll('img').length;
})()""")
            ab(['scroll', 'down', '400'])
            time.sleep(1)
            ab(['scroll', 'up', '200'])
            time.sleep(1)
        js = """
(() => {
  const seen = new Set(); const imgs = [];
  document.querySelectorAll('img').forEach(im => {
    if (!/userapi|impg/.test(im.src) || /N0puPWQhpFg/.test(im.src)) return;
    const base = im.src.split('?')[0];
    if (seen.has(base)) return;
    // берём даже мелкие: это могут быть превью; качество проверим по URL
    seen.add(base); imgs.push({src: im.src, w: im.naturalWidth || 0});
  });
  window.__imgs = imgs;
  return 'ok';
})()"""
        ab_eval(js)
        raw = ab_eval('JSON.stringify(window.__imgs)')
        arr = json.loads(raw)
        print(pid, '->', len(arr), 'imgs')
        for x in arr:
            print('   ', x['w'], x['src'][:100])
        out[pid] = arr
    json.dump(out, open('/home/z/my-project/vk_imgs_missed.json', 'w'), ensure_ascii=False, indent=1)
    print('saved')
