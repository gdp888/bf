#!/usr/bin/env python3
"""Добираем пропущенные посты ВК: обход по прямым ссылкам /wall-XXXX."""
import json
import subprocess
import sys
import time

BASE = '/home/z/my-project'
GROUP_ID = '223846998'
MISSED = ['1373', '1365', '1358', '1345', '1335', '1329', '1326',
          '1321', '1317', '1316', '1314', '1311', '1307', '1299']


def ab(cmd, timeout=60):
    r = subprocess.run(['agent-browser'] + cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def ab_eval(js, timeout=60):
    out = ab(['eval', js], timeout)
    if out.startswith('"') and out.endswith('"'):
        out = json.loads(out)
    return out


if __name__ == '__main__':
    # переиспользуем уже открытую сессию браузера
    ab(['open', f'https://vk.ru/wall-{GROUP_ID}_{MISSED[0]}'])
    ab(['wait', '--load', 'networkidle'])
    time.sleep(2)

    out_path = f'{BASE}/vk_details_missed.jsonl'
    open(out_path, 'w').close()
    for pid in MISSED:
        ab(['open', f'https://vk.ru/wall-{GROUP_ID}_{pid}'])
        ab(['wait', '--load', 'networkidle'])
        time.sleep(1.5)
        ab(['scroll', 'down', '600'])
        time.sleep(1)
        js = """
(() => {
  const art = document.querySelector('[data-post-id="-%ID%_%PID%"]') || document.querySelector('article');
  const wall = (art && (art.querySelector('.wall_text') || art.querySelector('.wall_post_cont'))) || art;
  const txt = ((wall && wall.innerText) || '').trim();
  let date = '';
  const rd = document.querySelector('.rel_date, time');
  if (rd) date = rd.innerText.trim();
  if (!date) {
    for (const a of document.querySelectorAll('a')) {
      const t = (a.innerText || '').trim();
      if (/^\\d{1,2}\\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/.test(t) && t.length < 20) { date = t; break; }
    }
  }
  const seen = new Set(); const imgs = [];
  document.querySelectorAll('img').forEach(im => {
    if (!/userapi|impg/.test(im.src) || /N0puPWQhpFg/.test(im.src)) return;
    const base = im.src.split('?')[0];
    if (seen.has(base) || (im.naturalWidth && im.naturalWidth < 130)) return;
    seen.add(base); imgs.push(im.src);
  });
  window.__p = {id: '%PID%', txt: txt.slice(0, 5000), date, imgs};
  return 'ok';
})()""".replace('%ID%', GROUP_ID).replace('%PID%', pid)
        ab_eval(js)
        raw = ab_eval('JSON.stringify(window.__p)')
        with open(out_path, 'a') as f:
            f.write(raw + '\n')
        p = json.loads(raw) if raw.startswith('{') else json.loads(json.loads(raw))
        print(f'{pid}: txt_len={len(p.get("txt") or "")} imgs={len(p.get("imgs") or [])} date={p.get("date")}')
    print('done ->', out_path)
