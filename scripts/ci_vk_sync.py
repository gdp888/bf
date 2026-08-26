#!/usr/bin/env python3
"""
CI-синхронизация постов VK -> сайт (запускается GitHub Actions по расписанию).

Алгоритм:
  1. Headless Chromium (Playwright) открывает группу vk.ru/dostigenie_deti
     и скроллит ленту, собирая id постов.
  2. Новые id (которых нет в src/data/fund.json) обходятся по прямым
     ссылкам: текст, дата, реакции, фото.
  3. Фото скачиваются в public/images (HD: параметр cs= поднимается
     до максимума из списка as=).
  4. Посты дописываются в src/data/fund.json, id пересчитываются.
  5. Изменения коммитит отдельный шаг workflow.

Правила отбора:
  - клипы и фотоленты без текста (<60 символов) пропускаются;
  - за один запуск обрабатывается не более MAX_POSTS_PER_RUN новых постов;
  - существующие посты и истории детей не трогаются.
"""
import json
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FUND_JSON = ROOT / 'src' / 'data' / 'fund.json'
IMG_DIR = ROOT / 'public' / 'images'

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
MONTHS_RU_GEN = {1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
                 5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
                 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'}

TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

BOLD_PATTERNS = ['вместе мы сделаем мир добрее', 'сбор закрыт',
                 'напоминаем', 'примите участие', 'обращаемся к каждому',
                 'мы просим вас о помощи', 'давайте усилимся']

MSK = timezone(timedelta(hours=3))


def log(msg):
    print(msg, flush=True)


def parse_vk_date(rel: str) -> str:
    """'17 Aug at 10:40 am' / 'сегодня в 12:00' / 'yesterday at ...' -> '17 августа 2026'."""
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
            return f'{day} {MONTHS_RU_GEN[month]} {year}'
    if any(w in rel for w in ('yesterday', 'вчера')):
        d = now - timedelta(days=1)
        return f'{d.day} {MONTHS_RU_GEN[d.month]} {d.year}'
    if any(w in rel for w in ('today', 'сегодня', 'minute', 'hour',
                              'минут', 'час')):
        return f'{now.day} {MONTHS_RU_GEN[now.month]} {now.year}'
    return f'{now.day} {MONTHS_RU_GEN[now.month]} {now.year}'


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


def make_title(txt: str) -> str:
    emoji = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F#]')
    for line in txt.split('\n'):
        s = emoji.sub('', line).strip().strip('•-— ')
        s = re.sub(r'\s+', ' ', s)
        if len(s) >= 12:
            if len(s) > 70:
                s = s[:70].rsplit(' ', 1)[0] + '…'
            return s
    return 'Новость фонда'


def make_slug(title: str, vk_id: str, existing: set) -> str:
    s = title.lower()
    s = ''.join(TRANSLIT.get(ch, ch) for ch in s)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    s = re.sub(r'-{2,}', '-', s)[:60].rstrip('-') or 'post'
    if s in existing:
        s = f'{s}-vk{vk_id}'
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


def apply_bold(txt: str) -> str:
    out = []
    for ln in txt.split('\n'):
        s = ln.strip()
        if s and len(s) < 120 and not s.startswith('**') and \
                any(p in s.lower() for p in BOLD_PATTERNS):
            out.append(f'**{s}**')
        else:
            out.append(ln)
    return '\n'.join(out)


def short_content(t: str, limit: int = 220) -> str:
    first = t.split('\n\n')[0] if '\n\n' in t else t
    s = re.sub(r'\s+', ' ', first).strip()
    if len(s) > limit:
        s = s[:limit].rsplit(' ', 1)[0] + '…'
    return s


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
  const byId = document.querySelector('[data-post-id="-%GID%_%PID%"]');
  const art = byId || document.querySelector('article');
  const wall = (art && (art.querySelector('.wall_text')
             || art.querySelector('.wall_post_cont')))
             || document.querySelector('.wall_text')
             || document.querySelector('.wall_post_cont')
             || art;
  const txt = ((wall && wall.innerText) || '').trim();
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
  const seen = new Set(); const imgs = [];
  document.querySelectorAll('img').forEach(im => {
    if (!/vkuserphoto|userapi|impg/.test(im.src)) return;
    if ((im.naturalWidth || 0) < 200) return;
    const base = im.src.split('?')[0];
    if (seen.has(base)) return;
    seen.add(base); imgs.push(im.src);
  });
  return {txt: txt.slice(0, 5000), date: date, imgs: imgs};
})()
""".replace('%GID%', GROUP_ID)


def fetch_images(vk_id: str, urls: list) -> list:
    media = []
    headers = {'User-Agent': UA, 'Referer': 'https://vk.ru/'}
    for i, src in enumerate(urls, 1):
        ext = '.png' if '.png' in src.split('?')[0] else '.jpg'
        fname = f'post-{vk_id}-{i:02d}{ext}'
        fpath = IMG_DIR / fname
        try:
            r = requests.get(upgrade_url(src), headers=headers, timeout=30)
            if r.ok and len(r.content) > 3000:
                fpath.write_bytes(r.content)
                media.append({
                    'type': 'image',
                    'url': f'/images/{fname}',
                    'alt': '',
                    'caption': '',
                })
                log(f'    img ok: {fname} ({len(r.content) // 1024} KB)')
        except Exception as e:
            log(f'    img fail: {e}')
    return media


def feed_reacts(feed: dict, pid: str) -> str:
    item = feed.get(f'-{GROUP_ID}_{pid}') or {}
    return item.get('reacts', '') or ''


def main() -> int:
    data = json.loads(FUND_JSON.read_text(encoding='utf-8'))
    known = {str(p.get('vk_id')) for p in data['posts']}
    known_slugs = {p['slug'] for p in data['posts']}
    seen_fps = {fingerprint(p.get('full_content', '')) for p in data['posts']}
    seen_fps.discard('')
    log(f'known posts: {len(known)}')

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
                time.sleep(2.5)
                page.evaluate('window.scrollBy(0, 700)')
                time.sleep(1.2)
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
            date = parse_vk_date(det.get('date', ''))

            title = make_title(txt)
            slug = make_slug(title, pid, known_slugs)
            known_slugs.add(slug)
            txt = apply_bold(txt)

            created.append({
                'id': 0,
                'vk_id': pid,
                'slug': slug,
                'date': date,
                'type': post_type,
                'title': title,
                'content': short_content(txt),
                'full_content': txt,
                'reactions': int(feed_reacts(feed, pid) or 0),
                'comments_count': 0,
                'shares': 0,
                'has_video': has_video,
                'video_duration': dur or None,
                'tags': [],
                'author': 'БФ «Достижение-Дети»',
                'commenters': [],
                'media': media,
                'vk_url': f'https://vk.ru/wall-{GROUP_ID}_{pid}',
            })
            log(f'  OK: [{post_type}] {title[:60]} imgs={len(media)}')

        browser.close()

    if not created:
        log('NO_NEW_POSTS (все новые id отсеяны по правилам)')
        return 0

    # --- 4. мерж в fund.json ---
    all_posts = data['posts'] + created
    all_posts.sort(key=lambda p: int(p['vk_id']), reverse=True)
    for i, p in enumerate(all_posts, 1):
        p['id'] = i
    data['posts'] = all_posts
    data['parsed_at'] = datetime.now(MSK).strftime('%Y-%m-%d')
    FUND_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    log(f'MERGED: +{len(created)} posts, total {len(all_posts)}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
