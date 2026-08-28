#!/usr/bin/env python3
"""
Миграция URL: качественные ЧПУ для всех постов ленты.

Было:  /2026-08-25-mypomogaemsamirueto  (слова склеены, транслит съел пробелы)
Стало: /news/2026-08-25-my-pomogaem-samiru/  (дата + дефисы + стоп-слова отфильтрованы)

Правила:
  - слаг = дата поста + до 6 значимых слов (транслит, дефисы, без стоп-слов);
  - посты без текста: video-<id> / foto-<id> / post-<id>;
  - коллизии (два поста в один день с одинаковыми словами) -> суффикс -<vk_id>;
  - каждому посту добавляются title (чистый <title> без эмодзи) и description (meta);
  - stories.post_slug перемапливаются на новые слаги через vk_id;
  - fund.json.posts удаляется (мёртвые данные после сноса роута /posts/*);
  - all_posts.json сортируется по дате (новые сверху).
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALL_POSTS = ROOT / 'src' / 'data' / 'all_posts.json'
FUND_JSON = ROOT / 'src' / 'data' / 'fund.json'
REPORT = ROOT / 'worklog' / 'data' / 'url_migration.json'

TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

# предлоги/союз/местоимения — мусор для URL, фильтруем ДО транслита
STOP_RU = {
    'в', 'во', 'и', 'с', 'со', 'к', 'ко', 'о', 'об', 'от', 'до', 'из', 'за',
    'на', 'по', 'для', 'при', 'у', 'не', 'ни', 'но', 'а', 'же', 'бы', 'ли',
    'или', 'да', 'мы', 'вы', 'они', 'оно', 'это', 'эта', 'эти', 'тот', 'та',
    'те', 'как', 'что', 'чтобы', 'есть', 'был', 'была', 'было', 'были',
    'ещё', 'еще', 'уже', 'нас', 'нам', 'вас', 'вам', 'его', 'её', 'ее', 'их',
    'им', 'мой', 'моя', 'наши', 'наш', 'вот', 'так', 'там', 'тут', 'очень',
    'много', 'мало', 'тоже', 'потом', 'тогда', 'чтобы',
}

MONTHS_RU_GEN = {1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
                 5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
                 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'}

# эмодзи и прочие символы, которых не должно быть в url/title/description
EMOJI_RE = re.compile(
    '[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF'
    '\uFE0F\u200D\u2B50\u2705\u2764\u2728\u2757\u2755\u2753\u2754\u26A1'
    '\u2934\u2935\u3030\u303D\u3297\u3299\u2194-\u21AA\u231A-\u231B\u2328'
    '\u23CF\u23E9-\u23FA\u24C2\u25AA-\u25FE\u2600-\u27BF\u203C\u2049]')


def strip_emoji(t: str) -> str:
    # выкидываем также модификаторы и Variation Selector
    out = ''.join(ch for ch in t if not unicodedata.combining(ch))
    out = EMOJI_RE.sub(' ', out)
    return out


def ru_date(iso_date: str) -> str:
    y, m, d = iso_date.split('-')
    return f'{int(d)} {MONTHS_RU_GEN[int(m)]} {y}'


def slug_words(text: str, max_words: int = 6, budget: int = 52) -> str:
    """До 6 значимых слов через дефис, транслит, стоп-слова прочь."""
    t = strip_emoji(text or '').lower()
    # токенизируем по-русски, стоп-слова фильтруем в оригинале
    tokens = re.split(r'[^0-9a-zа-яё]+', t)
    kept = []
    for w in tokens:
        if not w or w in STOP_RU:
            continue
        if len(w) == 1 and not w.isdigit():
            continue
        kept.append(w)
        if len(kept) >= max_words:
            break
    # транслит и сборка с бюджетом длины
    out = []
    for w in kept:
        tw = ''.join(TRANSLIT.get(ch, ch) for ch in w)
        tw = re.sub(r'[^a-z0-9]+', '', tw)
        if not tw:
            continue
        cand = '-'.join(out + [tw])
        if len(cand) > budget:
            break
        out.append(tw)
    return '-'.join(out)


def make_title(text: str, fallback: str) -> str:
    """Чистый заголовок: первая строка без эмодзи >= 12 симв, <= 70."""
    for line in (text or '').split('\n'):
        s = strip_emoji(line).strip().strip('•-—|').strip()
        s = re.sub(r'\s+', ' ', s).strip(' .,!?:;()«»"\'')
        s = re.sub(r'\s+([.,!?:;])', r'\1', s)  # ' . ' -> '. ' (после эмодзи)
        if len(s) >= 12:
            if len(s) > 70:
                s = s[:70].rsplit(' ', 1)[0]
            return s.rstrip(' —–-')  # после обрезки тоже может остаться '—'
    return fallback


def make_description(text: str, fallback: str) -> str:
    s = re.sub(r'\s+', ' ', strip_emoji(text or '')).strip()
    s = re.sub(r'\s+([.,!?:;])', r'\1', s)
    if len(s) > 160:
        s = s[:160].rsplit(' ', 1)[0] + '…'
    return s or fallback


def main():
    posts = json.loads(ALL_POSTS.read_text(encoding='utf-8'))
    fund = json.loads(FUND_JSON.read_text(encoding='utf-8'))

    # --- 1. новые слаги + title/description ---
    seen = set()
    mapping = []
    collisions, textless = [], []
    for p in posts:
        old_slug = p['slug']
        date = (p.get('date') or '')[:10]
        text = p.get('text') or ''
        has_videos = bool(p.get('videos'))
        n_imgs = len(p.get('images') or [])

        words = slug_words(text)
        if words:
            new_slug = f'{date}-{words}'
        elif has_videos:
            new_slug = f'{date}-video-{p["id"]}'
            textless.append((old_slug, new_slug, 'video'))
        elif n_imgs:
            new_slug = f'{date}-foto-{p["id"]}'
            textless.append((old_slug, new_slug, 'foto'))
        else:
            new_slug = f'{date}-post-{p["id"]}'
            textless.append((old_slug, new_slug, 'post'))

        if new_slug in seen:  # два поста в один день с теми же словами
            new_slug = f'{new_slug}-{p["id"]}'
            collisions.append(new_slug)
        seen.add(new_slug)

        # fallback-заголовки для постов без текста
        if text.strip():
            title = make_title(text, 'Новость фонда')
            desc = make_description(text, 'Новость благотворительного фонда «Достижение-Дети».')
        elif has_videos:
            title = f'Видео фонда — {ru_date(date)}'
            desc = f'Видеопубликация благотворительного фонда «Достижение-Дети» от {ru_date(date)}. Оригинал — в нашей группе ВКонтакте.'
        elif n_imgs:
            title = f'Фотоотчёт фонда — {ru_date(date)}'
            desc = f'Фотоотчёт благотворительного фонда «Достижение-Дети» от {ru_date(date)}.'
        else:
            title = f'Публикация фонда — {ru_date(date)}'
            desc = 'Публикация благотворительного фонда «Достижение-Дети».'

        p['slug'] = new_slug
        p['title'] = title
        p['description'] = desc
        mapping.append({'id': p['id'], 'old': old_slug, 'new': new_slug,
                        'title': title})

    # сортировка: новые сверху (дата desc, при равенстве — id desc)
    posts.sort(key=lambda p: ((p.get('date') or ''), int(p['id'])), reverse=True)

    # контроль длины и формата
    bad_len = [m['new'] for m in mapping if len(m['new']) > 64 or not re.fullmatch(r'[a-z0-9\-]+', m['new'])]
    assert not bad_len, f'некорректные слаги: {bad_len[:5]}'
    assert len({p["slug"] for p in posts}) == len(posts), 'слаги не уникальны!'

    ALL_POSTS.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')

    # --- 2. stories: перемап post_slug на новые слаги ---
    # fund.json posts (20 шт): старый слаг -> vk_id -> новый слаг из all_posts
    old_slug_to_vk = {p['slug']: str(p['vk_id']) for p in fund.get('posts', [])}
    vk_to_new = {str(p['id']): p['slug'] for p in posts}
    remap_log = []
    for s in fund.get('stories', []):
        old = s['post_slug']
        vk = old_slug_to_vk.get(old)
        new = vk_to_new.get(vk) if vk else None
        if new:
            s['post_slug'] = new
            remap_log.append({'story': s['name'], 'old': old, 'new': new})
        else:
            remap_log.append({'story': s['name'], 'old': old, 'new': None,
                              'ERROR': 'не найден пост в all_posts'})

    # --- 3. чистим fund.json от мёртвых posts ---
    removed_posts = len(fund.get('posts', []))
    fund.pop('posts', None)
    fund.pop('parsed_at', None)
    FUND_JSON.write_text(
        json.dumps(fund, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')

    # --- 4. отчёт ---
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        'total': len(posts),
        'mapping': mapping,
        'collisions': collisions,
        'textless': [t[1] for t in textless],
        'stories_remap': remap_log,
        'removed_fund_posts': removed_posts,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(f'OK: {len(posts)} постов, новые слаги + title + description')
    print(f'Коллизий (суффикс -id): {len(collisions)}')
    print(f'Без текста: {len(textless)}')
    print(f'fund.json: удалено {removed_posts} мёртвых постов')
    print('Stories remap:')
    for r in remap_log:
        mark = 'OK ' if r.get('new') else '!!!'
        print(f'  {mark} {r["story"]}: {r["old"]} -> {r["new"]}')
    print()
    print('Примеры новых URL:')
    for m in mapping[:10]:
        print(f'  /news/{m["new"]}/')
        print(f'      title: {m["title"][:60]}')


if __name__ == '__main__':
    main()
