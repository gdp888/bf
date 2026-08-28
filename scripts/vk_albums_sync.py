#!/usr/bin/env python3
"""
Парсер фотоальбомов группы БФ «Достижение-Дети» (vk.ru/dostigenie_deti).

Алгоритм (мобильная версия m.vk.ru открывается без логина):
  1. /albums-223846998 — список альбомов (id, название, счётчик).
  2. /album-223846998_<id> — скроллим до конца ленивой загрузки, из DOM
     собираем пары (photo_id, url превью с параметром as=...).
  3. Скачиваем HD: cs= в URL поднимаем до максимума из списка as=
     (тот же приём, что в ci_vk_sync.py для фото постов).
  4. Конвертация в WebP (max 1400px, q80) -> repo-bf/public/images/albums/.
  5. Итог: repo-bf/src/data/albums.json + сырой сырец URLs (для ретраев).

Скрипт докачиваемый: существующие WebP пропускаются, сырец URLs
(albums_raw.json) позволяет перезапустить только фазу скачивания.
"""
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / 'public' / 'images' / 'albums'
ALBUMS_JSON = ROOT / 'src' / 'data' / 'albums.json'
RAW_JSON = Path(__file__).resolve().parent / "albums_raw.json"

GROUP_ID = '223846998'
WEBP_MAX_DIM = 1400
WEBP_QUALITY = 80
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
HDRS = {'User-Agent': UA, 'Referer': 'https://vk.ru/'}

PHASE = sys.argv[1] if len(sys.argv) > 1 else 'all'   # all | parse | download


def log(msg):
    print(msg, flush=True)


def upgrade_url(url: str) -> str:
    """cs= (целиком, включая пайпы '640x0|640|793') -> максимальный размер из as=."""
    m = re.search(r'as=([0-9x,]+)', url)
    if m:
        best = m.group(1).split(',')[-1]
        if re.search(r'cs=[^&]+', url):
            return re.sub(r'cs=[^&]+', f'cs={best}', url)
        sep = '&' if '?' in url else '?'
        return url + f'{sep}cs={best}'
    return url


def to_webp(content: bytes):
    im = Image.open(io.BytesIO(content))
    if getattr(im, 'is_animated', False):
        return content, '.gif'
    im = ImageOps.exif_transpose(im)
    w, h = im.size
    scale = WEBP_MAX_DIM / max(w, h)
    if scale < 1:
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                       Image.LANCZOS)
    if im.mode not in ('RGB', 'L'):
        im = im.convert('RGBA')
    buf = io.BytesIO()
    im.save(buf, 'WEBP', quality=WEBP_QUALITY, method=4)
    return buf.getvalue(), '.webp'


# ---------------------------------------------------------------- фаза 1: разбор

def parse_albums():
    albums = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'])
        ctx = browser.new_context(
            **pw.devices['Pixel 7'],
            locale='ru-RU',
            timezone_id='Europe/Moscow')
        page = ctx.new_page()

        # --- список альбомов ---
        log('open albums list: m.vk.ru/albums-223846998')
        page.goto(f'https://m.vk.ru/albums-{GROUP_ID}',
                  wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(4000)
        items = page.query_selector_all(f'a[href*="/album-{GROUP_ID}_"]')
        for el in items:
            href = el.get_attribute('href') or ''
            m = re.search(rf'album-{GROUP_ID}_(\d+)', href)
            txt = ' '.join(el.inner_text().split())
            if not m:
                continue
            # «Название 12 фотографий» / «Название 1 фотография»
            tm = re.match(r'^(.*?)\s+(\d+)\s+фото', txt)
            title = (tm.group(1) if tm else txt).strip() or 'Альбом'
            count = int(tm.group(2)) if tm else 0
            albums.append({'id': m.group(1), 'title': title, 'count': count})
        log(f'albums found: {len(albums)}')

        # --- каждый альбом: скролл + сбор фото ---
        for alb in albums:
            url = f'https://m.vk.ru/album-{GROUP_ID}_{alb["id"]}'
            log(f'open album {alb["title"]!r} ({url})')
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
            except Exception as e:
                log(f'  SKIP: {e}')
                alb['photos'] = []
                continue
            page.wait_for_timeout(3000)

            prev, stable = 0, 0
            for i in range(60):
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(1200)
                n = page.evaluate(
                    f'document.querySelectorAll(\'a[href*="/photo-{GROUP_ID}_"]\').length')
                if n == prev:
                    stable += 1
                    if stable >= 3:
                        break
                else:
                    stable = 0
                prev = n
            log(f'  scrolled: {prev} photo tiles')

            photos = page.evaluate("""
            (() => {
              const out = [];
              document.querySelectorAll('a[href*="/photo-%GID%_"]').forEach(a => {
                const m = (a.getAttribute('href') || '').match(/photo-%GID%_(\\d+)/);
                const div = a.querySelector('[data-src_big],[style*="vkuserphoto"]');
                let src = '';
                if (div) {
                  src = div.getAttribute('data-src_big') || '';
                  if (!src) {
                    const bg = (div.getAttribute('style') || '').match(/url\\(([^)]+)\\)/);
                    if (bg) src = bg[1].replace(/["']/g, '');
                  }
                }
                if (m && src.includes('vkuserphoto')) {
                  out.push({id: m[1], src: src});
                }
              });
              return out;
            })()
            """.replace('%GID%', GROUP_ID))

            # dedupe с сохранением порядка
            seen, uniq = set(), []
            for p in photos:
                if p['id'] not in seen:
                    seen.add(p['id'])
                    uniq.append(p)
            alb['photos'] = uniq
            log(f'  photos collected: {len(uniq)} (vk said {alb["count"]})')
            time.sleep(1)

        browser.close()

    RAW_JSON.write_text(json.dumps(albums, ensure_ascii=False, indent=1),
                        encoding='utf-8')
    total = sum(len(a['photos']) for a in albums)
    log(f'PARSE DONE: {len(albums)} albums, {total} photos -> {RAW_JSON}')
    return albums


# ------------------------------------------------------------- фаза 2: скачивание

def fetch_one(alb_id: str, photo: dict) -> dict:
    pid = photo['id']
    fname = f'a{alb_id}-{pid}'
    webp = IMG_DIR / (fname + '.webp')
    if webp.exists() and webp.stat().st_size > 3000:
        return {'ok': True, 'id': pid, 'file': webp.name, 'cached': True}
    url = upgrade_url(photo['src'].replace('&amp;', '&'))
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HDRS, timeout=60)
            if r.ok and len(r.content) > 3000:
                content, ext = to_webp(r.content)
                fpath = IMG_DIR / (fname + ext)
                fpath.write_bytes(content)
                return {'ok': True, 'id': pid, 'file': fpath.name,
                        'kb': len(content) // 1024}
            log(f'    bad response {r.status_code} for {pid}')
        except Exception as e:
            log(f'    err {pid}: {e}')
        time.sleep(2 + attempt * 3)
    return {'ok': False, 'id': pid}


def download_all(albums):
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for alb in albums:
        ok = fail = cached = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_one, alb['id'], p): p for p in alb['photos']}
            for f in as_completed(futs):
                r = f.result()
                if r['ok']:
                    ok += 1
                    cached += 1 if r.get('cached') else 0
                else:
                    fail += 1
        dt = time.time() - t0
        log(f'  [{alb["title"]}] ok={ok} (cached={cached}) fail={fail} '
            f'in {dt:.0f}s')
        result.append({'album': alb['title'], 'ok': ok, 'fail': fail})
    return result


# ------------------------------------------------------------------------ итог

def build_json(albums):
    # защита: пустой разбор (VK заблокировал / сменил вёрстку) не должен
    # затирать уже собранную галерею
    if not any(alb.get('photos') for alb in albums) and ALBUMS_JSON.exists():
        log('EMPTY PARSE: сохраняю существующий albums.json')
        return
    # накопленные богатые данные (description/date/text из VK API, слитые
    # из выгрузки с токеном) переносим в новую версию файла, не теряем
    rich = {}
    if ALBUMS_JSON.exists():
        try:
            for old in json.loads(ALBUMS_JSON.read_text(encoding='utf-8')):
                rich[old['id']] = old
        except Exception:
            pass
    out = []
    for alb in albums:
        # альбом 0 — «Фотографии со страницы сообщества» (аватар/обложка,
        # уже есть на сайте как fund-avatar) — в галерею не берём
        if alb['id'] == '0':
            continue
        prev = rich.get(alb['id'], {})
        prev_photos = {str(p.get('id')): p for p in prev.get('photos', [])}
        photos = []
        for p in alb['photos']:
            webp = IMG_DIR / f'a{alb["id"]}-{p["id"]}.webp'
            if webp.exists():
                item = {'id': p['id'],
                        'src': f'/images/albums/{webp.name}'}
                # переносим дату/подпись, если были
                for k in ('date', 'text'):
                    if prev_photos.get(p['id'], {}).get(k):
                        item[k] = prev_photos[p['id']][k]
                photos.append(item)
        if photos:
            entry = {'id': alb['id'], 'title': alb['title'],
                     'count': len(photos), 'photos': photos}
            if prev.get('description'):
                entry['description'] = prev['description']
            out.append(entry)
    ALBUMS_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding='utf-8')
    log(f'albums.json: {len(out)} albums, '
        f'{sum(a["count"] for a in out)} photos -> {ALBUMS_JSON}')


def main():
    if PHASE in ('all', 'parse'):
        albums = parse_albums()
    else:
        albums = json.loads(RAW_JSON.read_text(encoding='utf-8'))
    if PHASE in ('all', 'download'):
        download_all(albums)
    build_json(albums)


if __name__ == '__main__':
    main()
