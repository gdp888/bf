#!/usr/bin/env python3
"""
CI-синхронизация постов VK -> сайт (запускается GitHub Actions по расписанию).

Алгоритм:
  1. Headless Chromium (Playwright) открывает группу vk.ru/dostigenie_deti
     и скроллит ленту, собирая id постов.
  2. Новые id (которых нет в src/data/all_posts.json) обходятся по прямым
     ссылкам: текст, дата, реакции, фото.
  3. Фото скачиваются в public/images/posts и конвертируются в WebP
     (max 1400px, q80 — как bulk-локализация; HD: параметр cs= поднимается
     до максимума из списка as=).
  4. Посты дописываются в src/data/all_posts.json — единый источник ленты
     /news. URL поста: /news/<дата>-<транслит-слова>/ (см. migrate_urls.py).
  5. Изменения коммитит отдельный шаг workflow.

Правила отбора:
  - клипы и фотоленты без текста (<60 символов) пропускаются;
  - за один запуск обрабатывается не более MAX_POSTS_PER_RUN новых постов;
  - существующие посты и истории детей не трогаются.
"""
import io
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

# общая логика слагов/заголовков — та же, что в миграции URL (скрипты в одной папке)
from migrate_urls import slug_words, make_title, make_description

ROOT = Path(__file__).resolve().parent.parent
ALL_POSTS_JSON = ROOT / 'src' / 'data' / 'all_posts.json'
IMG_DIR = ROOT / 'public' / 'images' / 'posts'

# параметры те же, что в bulk-локализации (scripts/localize_images.js снаружи репо)
WEBP_MAX_DIM = 1400
WEBP_QUALITY = 80

GROUP_URL = 'https://vk.ru/dostigenie_deti'
GROUP_ID = '223846998'
MAX_POSTS_PER_RUN = 8
MIN_TEXT_LEN = 60

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

MONTHS_EN = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
             'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
MONTHS_RU = {'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'мая': 5, 'июн': 6,
             'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12}
MSK = timezone(timedelta(hours=3))


def log(msg):
    print(msg, flush=True)


def parse_vk_date(rel: str) -> str:
    """'17 Aug at 10:40 am' / 'сегодня в 12:00' / 'yesterday at ...' -> 'YYYY-MM-DD 12:00'."""
    rel = (rel or '').strip().lower()
    now = datetime.now(MSK)
    m = re.search(r'(\d{1,2})\s+([a-zа-я]{3})', rel)
    if m:
        day, mon = int(m.group(1)), m.group(2)
        month = MONTHS_EN.get(mon) or MONTHS_RU.get(mon)
        if month:
            year = now.year
            if month > now.month + 1:
                year -= 1
            return f'{year:04d}-{month:02d}-{day:02d} 12:00'
    if any(w in rel for w in ('yesterday', 'вчера')):
        d = now - timedelta(days=1)
        return f'{d.year:04d}-{d.month:02d}-{d.day:02d} 12:00'
    return f'{now.year:04d}-{now.month:02d}-{now.day:02d} 12:00'


def clean_text(t: str) -> str:
    t = t.replace('\u00ad', '')
    t = re.sub(r'\s+([,.!?:;])', r'\1', t)
    t = re.sub(r'([«(\[])\s+', r'\1', t)
    t = re.sub(r'\s{2,}', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    junk = [r'Show more', r'Show likes', r'Show shared copies',
            r'Показать полностью[.…]*', r'Click to expand',
            r'^\s*БФ «Достижение-Дети»\s*·?\s*Author\s*$',
            r'^\s*post pinned\s*$', r'^\s*\d+ people reacted\s*$']
    keep = []
    for ln in t.split('\n'):
        s = ln.strip()
        if any(re.fullmatch(j, s, re.I) for j in junk):
            continue
        keep.append(ln)
    return '\n'.join(keep).strip()


def strip_duration(t: str):
    m = re.match(r'^(\d+:\d{2})\s*\n+', t)
    if m:
        return t[m.end():], m.group(1)
    return t, ''


# NB: make_title/make_description/slug_words — из migrate_urls.py
# (локальный дубль make_title удалён: затенял импорт и валил вызовы с fallback)

def make_slug(text: str, iso_date: str, vk_id: str, existing: set) -> str:
    """ЧПУ /news/<дата>-<слова>/: та же логика, что в migrate_urls.py."""
    words = slug_words(text)
    date = iso_date[:10]
    s = f'{date}-{words}' if words else f'{date}-post-{vk_id}'
    if s in existing:
        s = f'{s}-{vk_id}'
    return s


def detect_type(txt: str, n_imgs: int):
    """-> (type, has_video, video_duration, cleaned_text)
    Важно: видео (метка длительности в начале) проверяется первым —
    видеопосты с реквизитами не должны превращаться в call_to_action."""
    if re.match(r'^\s*\d+:\d{2}\s*\n', txt):
        txt, dur = strip_duration(txt)
        return 'video', True, dur, txt
    if re.search(r'р/с|реквизит|назначение платежа', txt, re.I):
        return 'call_to_action', False, '', txt
    if n_imgs >= 3:
        return 'event', False, '', txt
    return 'post', False, '', txt


def fingerprint(txt: str) -> str:
    """Агрессивная нормализация для сравнения постов-дублей.
    Метку длительности видео ('0:46') отбрасываем — иначе один и тот же
    видеопост с ней и без неё даст разные отпечатки."""
    txt = re.sub(r'^\s*\d+:\d{2}\s*', '', (txt or ''))
    return re.sub(r'[^a-zа-я0-9]+', '', txt.lower())[:100]


def upgrade_url(url: str) -> str:
    """Поднимаем разрешение фото: cs= -> максимальный размер из as=."""
    m = re.search(r'as=([0-9x,]+)', url)
    if m:
        best = m.group(1).split(',')[-1]
        return re.sub(r'cs=\d+x\d+', f'cs={best}', url)
    return url


COLLECT_JS = """
(() => {
  const out = {};
  document.querySelectorAll('[data-post-id]').forEach(art => {
    const id = art.getAttribute('data-post-id');
    if (!new RegExp('^-%GID%_\\\\d+$').test(id)) return;
    const c = art.querySelector('.wall_post_cont');
    const wall = art.querySelector('.wall_text');
    const txt = ((wall || c || {}).innerText || '').trim();
    const reacts = ((art.innerText || '').match(/(\\d+)\\s*(?:people reacted|реакци)/) || [])[1] || '';
    if (!out[id] || (out[id].txt || '').length < txt.length) {
      out[id] = {id: id, txt: txt.slice(0, 4000), reacts: reacts};
    }
  });
  return out;
})()
""".replace('%GID%', GROUP_ID)

DETAIL_JS_TEMPLATE = """
(() => {
  // Находим основной пост (не reply_dived - это репосты/комментарии)
  const byId = document.querySelector('[data-post-id="-%GID%_%PID%"]:not(.reply_dived)');
  const postEl = byId || document.querySelector('.post[data-post-id]:not(.reply_dived)') || document.querySelector('.post:not(.reply_dived)');
  
  // Текст ищем внутри .wall_text или .wall_post_cont внутри поста
  let txt = '';
  if (postEl) {
    const wallText = postEl.querySelector('.wall_text');
    const wallPostCont = postEl.querySelector('.wall_post_cont');
    txt = ((wallText || wallPostCont || postEl).innerText || '').trim();
  }
  
  // Дата из .rel_date или time
  let date = '';
  const rd = document.querySelector('.rel_date, time');
  if (rd) date = rd.innerText.trim();
  if (!date) {
    for (const a of document.querySelectorAll('a')) {
      const t = (a.innerText || '').trim();
      if (/^\\d{1,2}\\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/.test(t)
          && t.length < 20) { date = t; break; }
    }
  }
  
  // Картинки
  const seen = new Set(); const imgs = [];
  document.querySelectorAll('img').forEach(im => {
    if (!/vkuserphoto|userapi|impg/.test(im.src)) return;
    if ((im.naturalWidth || 0) < 200) return;
    const base = im.src.split('?')[0];
    if (seen.has(base)) return;
    seen.add(base); imgs.push(im.src);
  });
  // Видео: ссылки вида /video-<owner>_<id> внутри поста (для встроенного плеера)
  const vids = []; const seenV = new Set();
  document.querySelectorAll('a[href*="/video"]').forEach(a => {
    const m = (a.getAttribute('href') || '').match(/video(-\\d+)_(\\d+)/);
    if (!m) return;
    const key = m[1] + '_' + m[2];
    if (seenV.has(key)) return;
    seenV.add(key); vids.push({owner_id: Number(m[1]), id: Number(m[2])});
  });
  return {txt: txt.slice(0, 5000), date: date, imgs: imgs, vids: vids};
})()
""".replace('%GID%', GROUP_ID)


def to_webp(content: bytes):
    """JPEG/PNG -> WebP (max 1400px, q80). Анимированные GIF не трогаем -> (bytes, ext)."""
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


def fetch_images(vk_id: str, urls: list) -> list:
    media = []
    headers = {'User-Agent': UA, 'Referer': 'https://vk.ru/'}
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(urls, 1):
        fname = f'post-{vk_id}-{i:02d}'
        try:
            r = requests.get(upgrade_url(src), headers=headers, timeout=30)
            if r.ok and len(r.content) > 3000:
                content, ext = to_webp(r.content)
                fname += ext
                fpath = IMG_DIR / fname
                fpath.write_bytes(content)
                media.append({
                    'type': 'image',
                    'url': f'/images/posts/{fname}',
                    'alt': '',
                    'caption': '',
                })
                log(f'    img ok: {fname} ({len(content) // 1024} KB)')
        except Exception as e:
            log(f'    img fail: {e}')
    return media


def feed_reacts(feed: dict, pid: str) -> str:
    item = feed.get(f'-{GROUP_ID}_{pid}') or {}
    return item.get('reacts', '') or ''


# ------------------------------------------------------------- API-путь (VK_TOKEN)

def api_best_photo_url(photo: dict) -> str:
    """Максимальный размер из photo.sizes."""
    sizes = photo.get('sizes') or []
    if not sizes:
        return ''
    best = max(sizes, key=lambda s: s.get('width', 0) or 0)
    return best.get('url', '')


def api_best_image_url(images: list) -> str:
    """Максимальный превью-размер из video.image / video.first_frame."""
    if not images:
        return ''
    best = max(images, key=lambda s: s.get('width', 0) or 0)
    return best.get('url', '')


def api_download(url: str, fname_base: str) -> str:
    """Скачать и конвертировать в WebP -> относительный путь или ''."""
    headers = {'User-Agent': UA, 'Referer': 'https://vk.ru/'}
    try:
        r = requests.get(url, headers=headers, timeout=60)
        if not (r.ok and len(r.content) > 3000):
            log(f'    img bad response {r.status_code}')
            return ''
        content, ext = to_webp(r.content)
        fname = fname_base + ext
        (IMG_DIR / fname).write_bytes(content)
        log(f'    img ok: {fname} ({len(content) // 1024} KB)')
        return f'/images/posts/{fname}'
    except Exception as e:
        log(f'    img fail: {e}')
        return ''


def api_sync(data: list, known: set, known_slugs: set, seen_fps: set) -> list:
    """Синк через VK API (токен сообщества, env VK_TOKEN).

    Надёжнее Playwright-скрейпинга: точные даты, счётчики реакций,
    HD-фото и все видео-аттачи напрямую из wall.get.
    Возвращает список новых постов в формате all_posts.json.
    """
    token = os.environ.get('VK_TOKEN', '')
    api = 'https://api.vk.com/method/wall.get'
    items, offset = [], 0
    while True:
        r = requests.get(api, params={
            'owner_id': f'-{GROUP_ID}', 'count': 100, 'offset': offset,
            'v': '5.199', 'access_token': token}, timeout=30).json()
        if 'error' in r:
            raise RuntimeError(f"VK API error: {r['error']}")
        got = r['response']['items']
        items.extend(got)
        if len(got) < 100 or len(items) >= r['response']['count']:
            break
        offset += 100
        time.sleep(0.4)
    log(f'API: получили {len(items)} постов со стены')

    new_items = [it for it in items if str(it['id']) not in known]
    new_items.sort(key=lambda x: x['date'], reverse=True)
    new_items = new_items[:MAX_POSTS_PER_RUN]
    log(f'API: новых постов-кандидатов: {len(new_items)}')
    if not new_items:
        return []

    created = []
    for it in new_items:
        pid = str(it['id'])
        txt = clean_text(it.get('text', ''))
        if len(txt) < MIN_TEXT_LEN:
            log(f'  {pid}: skip, текст короткий ({len(txt)})')
            continue
        fp = fingerprint(txt)
        if fp and fp in seen_fps:
            log(f'  {pid}: skip, дубликат')
            continue
        seen_fps.add(fp)

        atts = it.get('attachments', [])
        # посты-репосты: текст берём из вложенной записи, если свой пуст
        if not txt and it.get('copy_history'):
            for ch in it['copy_history']:
                ch_txt = clean_text(ch.get('text', ''))
                if len(ch_txt) >= MIN_TEXT_LEN:
                    txt = ch_txt
                    atts = ch.get('attachments', [])
                    break
        if len(txt) < MIN_TEXT_LEN:
            log(f'  {pid}: skip, текст пуст')
            continue

        # фото
        images = []
        for i, a in enumerate([a for a in atts if a['type'] == 'photo'], 1):
            url = api_best_photo_url(a['photo'])
            if url:
                rel = api_download(url, f'post-{pid}-{i:02d}')
                if rel:
                    images.append(rel)

        # видео (ID + превью)
        videos = []
        for i, a in enumerate([a for a in atts if a['type'] == 'video'], 1):
            v = a['video']
            prev = api_best_image_url(v.get('image') or v.get('first_frame') or [])
            rel_prev = api_download(prev, f'video-{pid}-{i:02d}') if prev else ''
            # дефолтный англ. заголовок VK нормализуем как в остальных постах
            vtitle = v.get('title') or ''
            if vtitle.startswith('Video by'):
                vtitle = 'Видео от' + vtitle[len('Video by'):]
            videos.append({
                'title': vtitle or 'Видео от БФ «Достижение-Дети»',
                'duration': v.get('duration'),
                'image': rel_prev,
                'owner_id': v.get('owner_id'),
                'id': v.get('id'),
                'vk_url': f'https://vk.com/wall-{GROUP_ID}_{pid}',
            })

        # ссылки
        links = [{'url': a['link'].get('url'),
                  'title': a['link'].get('title', '')}
                 for a in atts if a['type'] == 'link']
        links = [l for l in links if l['url']]

        iso_date = datetime.fromtimestamp(it['date'], MSK).strftime(
            '%Y-%m-%d %H:%M')
        title = make_title(txt, 'Новость фонда')
        slug = make_slug(txt, iso_date, pid, known_slugs)
        known_slugs.add(slug)
        desc = make_description(
            txt, 'Новость благотворительного фонда «Достижение-Дети».')

        created.append({
            'id': it['id'],
            'date': iso_date,
            'text': txt,
            'images': images,
            'videos': videos,
            'links': links,
            'likes': (it.get('likes') or {}).get('count', 0),
            'comments': (it.get('comments') or {}).get('count', 0),
            'reposts': (it.get('reposts') or {}).get('count', 0),
            'views': (it.get('views') or {}).get('count', 0),
            'slug': slug,
            'title': title,
            'description': desc,
        })
        log(f'  OK: {pid} [{title[:50]}] imgs={len(images)} vids={len(videos)}')
    return created


def main() -> int:
    data = json.loads(ALL_POSTS_JSON.read_text(encoding='utf-8'))
    known = {str(p.get('id')) for p in data}
    known_slugs = {p['slug'] for p in data}
    seen_fps = {fingerprint(p.get('text', '')) for p in data}
    seen_fps.discard('')
    log(f'known posts: {len(known)}')

    # --- API-путь: быстро и надёжно, без браузера ---
    if os.environ.get('VK_TOKEN'):
        log('режим: VK API (VK_TOKEN задан)')
        try:
            created = api_sync(data, known, known_slugs, seen_fps)
        except Exception as e:
            log(f'API_SYNC_FAIL: {e} — переключаюсь на Playwright')
            created = []
        if created or not os.environ.get('VK_FALLBACK_PW'):
            if not created:
                log('NO_NEW_POSTS (API)')
                return 0
            return finish(data, created)
        log('API ничего не дал, пробуем Playwright-путь')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'])
        ctx = browser.new_context(
            user_agent=UA,
            viewport={'width': 1366, 'height': 900},
            locale='ru-RU',
            timezone_id='Europe/Moscow')
        page = ctx.new_page()

        # --- 1. лента группы ---
        log(f'open feed: {GROUP_URL}')
        page.goto(GROUP_URL, wait_until='domcontentloaded', timeout=60000)
        try:
            page.wait_for_selector('[data-post-id]', timeout=30000)
        except Exception:
            log('VK_BLOCKED: лента не загрузилась (защита VK или нет сети)')
            browser.close()
            return 0
        time.sleep(2)

        dbg = page.evaluate("""
(() => ({
  url: location.href,
  title: document.title,
  anyPostIds: document.querySelectorAll('[data-post-id]').length,
  sampleIds: [...document.querySelectorAll('[data-post-id]')]
              .slice(0, 6).map(e => e.getAttribute('data-post-id')),
  bodySnippet: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 250),
}))
""")
        log('DEBUG page: ' + json.dumps(dbg, ensure_ascii=False))

        feed = {}
        stale = 0
        for _ in range(25):
            page.evaluate('window.scrollBy(0, 900)')
            time.sleep(1.1)
            batch = page.evaluate(COLLECT_JS)
            before = len(feed)
            feed.update(batch)
            stale = 0 if len(feed) > before else stale + 1
            if stale >= 4:
                break
        log(f'feed collected: {len(feed)} posts')

        # --- 2. новые id ---
        def is_clip(item):
            # только по явным маркерам клипов (ru/en); пустой текст в ленте —
            # не повод отбрасывать: виртуализация VK вычищает текст из DOM,
            # реальный текст добирается на странице поста (порог MIN_TEXT_LEN)
            t = (item.get('txt') or '').lower()
            return 'original sound' in t or 'оригинал' in t

        new_ids = [it['id'].split('_')[-1] for it in feed.values()
                   if it['id'].split('_')[-1] not in known and not is_clip(it)]
        new_ids = sorted(set(new_ids), key=int,
                         reverse=True)[:MAX_POSTS_PER_RUN]
        log(f'new text posts to fetch: {new_ids}')
        if not new_ids:
            log('NO_NEW_POSTS')
            browser.close()
            return 0

        # --- 3. детали постов ---
        created = []
        for pid in new_ids:
            log(f'details: {pid}')
            try:
                page.goto(f'https://vk.ru/wall-{GROUP_ID}_{pid}',
                          wait_until='domcontentloaded', timeout=60000)
                # Ждём появления основного поста (не reply_dived)
                try:
                    page.wait_for_selector(f'[data-post-id="-{GROUP_ID}_{pid}"]:not(.reply_dived), .post:not(.reply_dived)', timeout=15000)
                except Exception:
                    pass
                time.sleep(3.0)
                page.evaluate('window.scrollBy(0, 700)')
                time.sleep(1.5)
                det = page.evaluate(DETAIL_JS_TEMPLATE)
            except Exception as e:
                log(f'  detail fail: {e}')
                continue
            raw_txt = det.get('txt', '')
            if len(raw_txt.strip()) < MIN_TEXT_LEN:
                log(f'  skip: text too short ({len(raw_txt.strip())})')
                continue
            txt = clean_text(raw_txt)
            if len(txt) < MIN_TEXT_LEN:
                log(f'  skip: text too short after clean ({len(txt)})')
                continue
            # дедуп: повторные посты (репосты) пропускаем ДО скачивания фото
            fp = fingerprint(txt)
            if fp and fp in seen_fps:
                log('  skip: дубликат уже существующего поста')
                continue
            seen_fps.add(fp)
            media = fetch_images(pid, det.get('imgs', []))
            post_type, has_video, dur, txt = detect_type(txt, len(media))
            iso_date = parse_vk_date(det.get('date', ''))

            title = make_title(txt, 'Новость фонда')
            slug = make_slug(txt, iso_date, pid, known_slugs)
            known_slugs.add(slug)
            desc = make_description(
                txt, 'Новость благотворительного фонда «Достижение-Дети».')

            created.append({
                'id': int(pid),
                'date': iso_date,
                'text': txt,
                'images': [m['url'] for m in media if m.get('type') == 'image'],
                'videos': ([{'title': title, 'duration': dur or None,
                             'image': '',
                             'owner_id': (det.get('vids') or [{}])[0].get('owner_id'),
                             'id': (det.get('vids') or [{}])[0].get('id'),
                             'vk_url': f'https://vk.ru/wall-{GROUP_ID}_{pid}'}]
                           if has_video else []),
                'links': [],
                'likes': int(feed_reacts(feed, pid) or 0),
                'comments': 0,
                'reposts': 0,
                'views': 0,
                'slug': slug,
                'title': title,
                'description': desc,
            })
            log(f'  OK: [{post_type}] {title[:60]} imgs={len(media)}')

        browser.close()

    if not created:
        log('NO_NEW_POSTS (все новые id отсеяны по правилам)')
        return 0
    return finish(data, created)


def finish(data: list, created: list) -> int:
    """Мерж в all_posts.json + отчёт в worklog/autosync.log."""
    all_posts = data + created
    all_posts.sort(key=lambda p: ((p.get('date') or ''), int(p['id'])), reverse=True)
    ALL_POSTS_JSON.write_text(
        json.dumps(all_posts, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    log(f'MERGED: +{len(created)} posts, total {len(all_posts)}')
    # отчёт в worklog/autosync.log — уйдёт в тот же автокоммит (история работы робота)
    stamp = datetime.now(MSK).strftime('%Y-%m-%d %H:%M МСК')
    rep = [f'{stamp} | +{len(created)} пост(ов) | id: {", ".join(str(p["id"]) for p in created)}']
    rep += [f'    {p["id"]}: {p["title"][:80]}' for p in created]
    with open(ROOT / 'worklog' / 'autosync.log', 'a', encoding='utf-8') as f:
        f.write('\n'.join(rep) + '\n')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
