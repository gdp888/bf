#!/usr/bin/env python3
"""
VK -> GitHub синхронизация контента фонда «Достижение-Дети».

Повторяемый пайплайн (требует установленный agent-browser + Chrome):
  1. Скроллит ленту https://vk.ru/dostigenie_deti, собирая посты
     (VK виртуализирует ленту, поэтому тексты собираются пошагово).
  2. Обходит каждый новый пост по прямой ссылке /wall-223846998_XXXX:
     полный текст, дата, реакции, фото.
  3. Скачивает фото локально в public/images/.
  4. Пересобирает src/data/fund.json (добавляя только НОВЫЕ посты).
  5. Коммит и пуш в GitHub.

Запуск:
  python3 scripts/vk_sync.py [--push]

Примечания:
  - VK отдаёт контент только отрендеренный в браузере (клаудфлер-подобная
    защита на HTML-запросах), поэтому используется headless-браузер.
  - Подписанные ссылки на фото VK протухают, поэтому фото храним локально.
"""
import json
import os
import re
import subprocess
import sys
import time

BASE = '/home/z/my-project'
REPO = f'{BASE}/repo-bf'
GROUP = 'https://vk.ru/dostigenie_deti'
GROUP_ID = '223846998'

IMG_DIR = f'{REPO}/public/images'


def ab(cmd, timeout=60):
    """Вызов agent-browser CLI."""
    r = subprocess.run(['agent-browser'] + cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def ab_eval(js, timeout=60):
    out = ab(['eval', js], timeout)
    # agent-browser возвращает строку в кавычках при JSON-ответе
    if out.startswith('"') and out.endswith('"'):
        out = json.loads(out)
    return out


MONTHS_RU = {
    'Jan': 'января', 'Feb': 'февраля', 'Mar': 'марта', 'Apr': 'апреля',
    'May': 'мая', 'Jun': 'июня', 'Jul': 'июля', 'Aug': 'августа',
    'Sep': 'сентября', 'Oct': 'октября', 'Nov': 'октября', 'Dec': 'декабря',
}


def parse_vk_date(rel: str, now=None) -> str:
    """'17 Aug at 10:40 am' / '13 Aug' / '40 minutes ago' -> '17 августа 2026'."""
    m = re.search(r'(\d{1,2})\s+([A-Za-z]{3})', rel)
    if m:
        day, mon = m.group(1), m.group(2)
        return f'{int(day)} {MONTHS_RU.get(mon, mon)} 2026'
    if 'minute' in rel or 'hour' in rel or 'сегодня' in rel:
        return 'сегодня'
    if 'yesterday' in rel or 'вчера' in rel:
        return 'вчера'
    return rel


def step1_collect_feed():
    """Скроллит ленту группы, собирает id/тексты/реакции."""
    ab(['open', GROUP])
    ab(['wait', '--load', 'networkidle'])
    time.sleep(2)
    ab_eval('window.__col = window.__col || {}; "init"')
    for _ in range(40):
        ab(['scroll', 'down', '600'])
        time.sleep(1.2)
        ab_eval("""
(() => {
  document.querySelectorAll('[data-post-id]').forEach(art => {
    const id = art.getAttribute('data-post-id');
    if (!new RegExp('^-%ID%_\\\\d+$').test(id)) return;
    if (!window.__col[id]) window.__col[id] = {id, txt:'', imgs:[], reacts:''};
    const c = art.querySelector('.wall_post_cont');
    const wall = art.querySelector('.wall_text');
    const txt = ((wall || c || {}).innerText || '').trim();
    if (txt.length > (window.__col[id].txt || '').length && !/Original sound/.test(txt)
        && !/Click to expand/.test(txt)) {
      window.__col[id].txt = txt.slice(0, 4000);
    }
    const reacts = ((art.innerText || '').match(/(\\d+)\\s*(?:people reacted|реакци)/) || [])[1] || '';
    if (reacts) window.__col[id].reacts = reacts;
  });
  return Object.keys(window.__col).length;
})()""".replace('%ID%', GROUP_ID))
    raw = ab_eval('JSON.stringify(Object.values(window.__col))')
    posts = json.loads(raw)
    json.dump(posts, open(f'{BASE}/vk_feed.json', 'w'), ensure_ascii=False, indent=1)
    return posts


def step2_fetch_details(new_ids):
    """Обходит каждый пост по ссылке, собирает полный текст/дату/фото."""
    out = f'{BASE}/vk_details.jsonl'
    open(out, 'w').close()
    for pid in new_ids:
        ab(['open', f'https://vk.ru/wall-{GROUP_ID}_{pid}'])
        ab(['wait', '--load', 'networkidle'])
        time.sleep(1.5)
        ab(['scroll', 'down', '600'])
        time.sleep(1)
        ab_eval("""
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
})()""".replace('%ID%', GROUP_ID).replace('%PID%', pid))
        raw = ab_eval('JSON.stringify(window.__p)')
        with open(out, 'a') as f:
            f.write(raw + '\n')
        print('details ok:', pid)


def step3_download_images():
    """Скачивает новые фото в public/images."""
    manifest = {}
    for line in open(f'{BASE}/vk_details.jsonl'):
        line = line.strip()
        if not line:
            continue
        p = json.loads(json.loads(line) if line.startswith('"') else line)
        pid = p['id']
        files = []
        for i, url in enumerate(p.get('imgs', []), 1):
            ext = '.png' if '.png' in url.split('?')[0] else '.jpg'
            fname = f'post-{pid}-{i:02d}{ext}'
            fpath = os.path.join(IMG_DIR, fname)
            if not os.path.exists(fpath):
                subprocess.run(['curl', '-sL', '--max-time', '25', '-o', fpath, url], capture_output=True)
            if os.path.exists(fpath) and os.path.getsize(fpath) > 3000:
                files.append(fname)
            elif os.path.exists(fpath):
                os.remove(fpath)
        if files:
            manifest[pid] = files
    json.dump(manifest, open(f'{BASE}/img_manifest.json', 'w'), ensure_ascii=False, indent=1)
    return manifest


def step4_update_fund_json():
    """Дополняет fund.json новыми постами (уже существующие не трогает)."""
    fund_path = f'{REPO}/src/data/fund.json'
    data = json.load(open(fund_path, encoding='utf-8'))
    known_vk = {p.get('vk_id') for p in data['posts']}
    details = []
    for line in open(f'{BASE}/vk_details.jsonl'):
        line = line.strip()
        if line:
            details.append(json.loads(json.loads(line) if line.startswith('"') else line))
    new = [d for d in details if d['id'] not in known_vk and d['txt'] and len(d['txt']) > 60]
    print(f'новых постов: {len(new)}')
    # Далее — ручная верификация: слаги/типы/заголовки новых постов
    # задаются в scripts/build_fund_json.py (META) и пересобираются им.
    return new


if __name__ == '__main__':
    push = '--push' in sys.argv
    print('[1/4] Сбор ленты...')
    feed = step1_collect_feed()
    ids = sorted({p['id'].split('_')[-1] for p in feed}, key=int, reverse=True)
    print('  постов в ленте:', len(ids))
    print('[2/4] Детали постов...')
    step2_fetch_details(ids)
    print('[3/4] Скачивание фото...')
    step3_download_images()
    print('[4/4] Обновление fund.json...')
    new = step4_update_fund_json()
    print('Готово. Дальше: заполнить META в build_fund_json.py для новых id,')
    print('запустить build_fund_json.py, npm run build и git push.')
