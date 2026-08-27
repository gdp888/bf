#!/usr/bin/env python3
"""Генерирует новый src/data/fund.json из спарсенных данных VK.

Безопасность данных: посты, добавленные автосинком CI (которых нет в META),
переносятся из текущего fund.json как есть (carry-over) + ассерт на потерю.

Скрипт работает из двух мест (см. worklog/README.md в репо):
  - локально: .../scripts/build_fund_json.py, снапшоты данных рядом;
  - из клона репо: <repo>/worklog/scripts/build_fund_json.py, снапшоты в ../data.
"""
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _find_base() -> Path:
    """Каталог со снапшотами данных (vk_posts_full.json и др.)."""
    cands = [Path(os.environ['FUND_DATA'])] if os.environ.get('FUND_DATA') else []
    cands += [HERE, HERE / 'data', HERE.parent / 'data', Path('/home/z/my-project')]
    for c in cands:
        if (c / 'vk_posts_full.json').exists():
            return c
    raise SystemExit('Не найдены снапшоты (vk_posts_full.json), искал в: '
                     + ', '.join(str(c) for c in cands))


def _find_repo() -> Path:
    env = os.environ.get('FUND_REPO')
    if env:
        return Path(env)
    if (HERE.parent / 'repo-bf').exists():      # локальная раскладка: scripts/ рядом с repo-bf/
        return HERE.parent / 'repo-bf'
    return HERE.parent.parent                   # в клоне репо: worklog/scripts -> корень репо


BASE = _find_base()
REPO = str(_find_repo())

posts_full = json.load(open(f'{BASE}/vk_posts_full.json', encoding='utf-8'))
post_1319 = json.load(open(f'{BASE}/post_1319.json', encoding='utf-8'))
post_1385 = json.load(open(f'{BASE}/post_1385.json', encoding='utf-8'))
manifest = json.load(open(f'{BASE}/img_manifest.json', encoding='utf-8'))
# добор ранее пропущенных постов (1316/1314/1311)
for _pid, _files in json.load(open(f'{BASE}/img_manifest_missed.json', encoding='utf-8')).items():
    manifest.setdefault(_pid, _files)
wall_posts = json.load(open(f'{BASE}/vk_wall_posts.json', encoding='utf-8'))

# детали пропущенных постов, собранные по прямым ссылкам
missed_details = []
for _line in open(f'{BASE}/vk_details_missed.jsonl'):
    _line = _line.strip()
    if _line:
        missed_details.append(json.loads(json.loads(_line) if _line.startswith('"') else _line))

# реакции из фида (ID вида -223846998_XXXX -> XXXX)
FEED_REACTS = {}
for p in wall_posts:
    short = p['id'].split('_')[-1]
    if p.get('reacts'):
        FEED_REACTS[short] = int(p['reacts'])
FEED_REACTS['1319'] = 26
FEED_REACTS.update({'1316': 23, '1314': 15, '1311': 16})
FEED_REACTS['1385'] = 0

old = json.load(open(f'{REPO}/src/data/fund.json', encoding='utf-8'))


def clean_text(t: str) -> str:
    t = t.replace('\u00ad', '')
    t = re.sub(r'\s+([,.!?:;])', r'\1', t)          # " ." -> "."
    t = re.sub(r'([«(\[])\s+', r'\1', t)
    t = re.sub(r'\s{2,}', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    # убрать UI-мусор
    junk = [r'Show more', r'Show likes', r'Show shared copies', r'Показать полностью[.…]*',
            r'Click to expand', r'^\s*БФ «Достижение-Дети»\s*·?\s*Author\s*$', r'^\s*post pinned\s*$']
    lines = t.split('\n')
    keep = []
    for ln in lines:
        s = ln.strip()
        if any(re.fullmatch(j, s) for j in junk):
            continue
        keep.append(ln)
    t = '\n'.join(keep)
    return t.strip()


def strip_duration(t: str) -> tuple[str, str]:
    m = re.match(r'^(\d+:\d{2})\s*\n+', t)
    if m:
        return t[m.end():], m.group(1)
    return t, ''


# ---------- метаданные постов ----------
META = {
    '1385': dict(slug='my-pomogaem-samiru-eto-malchik-s-bolshim-serdtsem-i-ogromnoy',
                 title='Мы помогаем Самиру — мальчик с большим сердцем и огромной мечтой',
                 type='video', date='25 августа 2026',
                 tags=['видео', 'сбор средств', 'реабилитация', 'Самир']),
    '1378': dict(slug='my-pomogaem-samiru-video-obrashchenie',
                 title='Мы помогаем Самиру — видеообращение о важном этапе',
                 type='video', date='27 августа 2026',
                 tags=['видео', 'сбор средств', 'реабилитация', 'Самир'],
                 comments=['Andrey Kiashko', 'Natalya Koscheeva', 'Anna Shtofel']),
    '1374': dict(slug='letniy-otdykh-s-detmi',
                 title='Летний отдых с детьми — моменты радости и счастья',
                 type='event', date='17 августа 2026',
                 tags=['мероприятие', 'летний отдых', 'дети', 'фотоотчёт'],
                 comments=['Anna Shtofel']),
    '1372': dict(slug='kazhdyi-mozhet-stat-chastyu-proektov',
                 title='Каждый из вас может стать частью наших проектов',
                 type='call_to_action', date='13 августа 2026',
                 tags=['сбор средств', 'помощь', 'реквизиты']),
    '1357': dict(slug='den-molodezhi-videootchet',
                 title='День молодёжи в Новокуйбышевске — видеоотчёт',
                 type='video', date='28 июля 2026',
                 tags=['видео', 'мероприятие', 'День молодёжи']),
    '1351': dict(slug='komanda-volonterov-fonda',
                 title='Команда волонтёров фонда — трудимся для детей',
                 type='post', date='27 июля 2026',
                 tags=['волонтёры', 'фонд', 'команда']),
    '1348': dict(slug='pomoshch-vane-reabilitatsiya',
                 title='Помощь Ване — сбор на реабилитацию',
                 type='video', date='25 июля 2026',
                 tags=['видео', 'сбор средств', 'реабилитация', 'Ваня']),
    '1341': dict(slug='den-zashchity-detey-foto',
                 title='Счастливые фото со Дня защиты детей',
                 type='event', date='17 июля 2026',
                 tags=['фотоотчёт', 'День защиты детей', 'праздник']),
    '1337': dict(slug='sbor-zakryt-saveliy',
                 title='Сбор закрыт: оплачен курс реабилитации для Савелия',
                 type='post', date='16 июля 2026',
                 tags=['сбор закрыт', 'Савелий', 'реабилитация', 'спасибо']),
    '1334': dict(slug='pomoshch-samiru-gabdullinu',
                 title='Помощь Самиру Габдуллину — история мальчика с большой мечтой',
                 type='pinned', date='10 июля 2026',
                 tags=['сбор средств', 'реабилитация', 'ДЦП', 'Самир']),
    '1331': dict(slug='den-semyi-lyubvi-i-vernosti',
                 title='День семьи, любви и верности',
                 type='post', date='8 июля 2026',
                 tags=['праздник', 'семья', 'День семьи']),
    '1327': dict(slug='vspominaem-yarkie-momenty',
                 title='Вспоминаем яркие моменты праздника',
                 type='event', date='6 июля 2026',
                 tags=['фотоотчёт', 'праздник', 'благодарность']),
    '1322': dict(slug='darim-podarki-radost',
                 title='Дарим подарки и радость нашим друзьям',
                 type='call_to_action', date='25 июня 2026',
                 tags=['подарки', 'помощь', 'реквизиты']),
    '1319': dict(slug='eva-reabilitatsiya-kazan',
                 title='Ева проходит реабилитацию в Казани',
                 type='post', date='22 июня 2026',
                 tags=['Ева', 'реабилитация', 'Казань', 'результаты']),
    '1316': dict(slug='master-klass-den-zashchity-detey',
                 title='Мастер-класс ко Дню защиты детей — сумки своими руками',
                 type='event', date='17 июня 2026',
                 tags=['мастер-класс', 'День защиты детей', 'творчество', 'фотоотчёт']),
    '1314': dict(slug='sbor-saveliy-napominaem',
                 title='Напоминаем: открыт сбор для Савелия на реабилитацию',
                 type='call_to_action', date='15 июня 2026',
                 tags=['сбор средств', 'Савелий', 'реабилитация', 'реквизиты']),
    '1311': dict(slug='den-rossii-zhit-i-tvorit',
                 title='День России — жить и творить в нашей стране',
                 type='post', date='12 июня 2026',
                 tags=['праздник', 'День России', 'поздравление']),
    '1301': dict(slug='den-zashchity-detey-novokuybyshevsk',
                 title='День защиты детей в Новокуйбышевске',
                 type='event', date='9 июня 2026',
                 tags=['мероприятие', 'День защиты детей', 'праздник']),
    '1289': dict(slug='s-dnem-zashchity-detey',
                 title='С Международным днём защиты детей!',
                 type='post', date='1 июня 2026',
                 tags=['праздник', 'День защиты детей', 'поздравление']),
    '1288': dict(slug='s-dnem-rozhdeniya-vanya',
                 title='С днём рождения, Ванечка!',
                 type='post', date='1 июня 2026',
                 tags=['день рождения', 'Ваня', 'поздравление']),
}

BOLD_PATTERNS = [
    'СБОР ЗАКРЫТ', 'Мы просим вас о помощи', 'Давайте усилимся',
    'Обращаемся к каждому', 'Примите участие', 'каждый может поддержать',
    'ВМЕСТЕ МЫ',
]


def short_content(t: str, limit: int = 220) -> str:
    first = t.split('\n\n')[0] if '\n\n' in t else t
    s = re.sub(r'\s+', ' ', first).strip()
    if len(s) > limit:
        s = s[:limit].rsplit(' ', 1)[0] + '…'
    return s


def build_media(pid: str, title: str) -> list:
    media = []
    for i, fname in enumerate(manifest.get(pid, []), 1):
        media.append({
            'type': 'image',
            'url': f'/images/{fname}',
            'alt': f'{title} — фото {i}',
            'caption': '',
        })
    return media


new_posts = []
src_by_id = {p['id']: p for p in posts_full}
src_by_id['1319'] = {'id': '1319', 'txt': post_1319['txt'], 'imgs': [], 'reacts': ''}
# пост 1385 (видео про Самира) добавлен автосинком CI — источник: сохранённый снимок
data_1385 = json.load(open(f'{BASE}/post_1385.json', encoding='utf-8'))
src_by_id['1385'] = {'id': '1385', 'txt': data_1385['full_content'], 'imgs': [], 'reacts': ''}
src_by_id.update({p['id']: p for p in missed_details})

for pid, meta in META.items():
    raw = src_by_id[pid]['txt']
    reacts = FEED_REACTS.get(pid, 0)
    txt = clean_text(raw)
    dur = ''
    if meta['type'] == 'video':
        txt, dur0 = strip_duration(txt)
        dur = dur0 or {'1378': '0:46', '1357': '0:33', '1348': '1:17', '1385': '0:46'}[pid]
    if pid == '1314':  # прикреплённое видео 0:42, но пост текстовый — убираем метку длительности
        txt = re.sub(r'^\s*\d+:\d{2}\s*\n+', '', txt)
    # выделение ключевых строк жирным
    lines = txt.split('\n')
    out_lines = []
    for ln in lines:
        s = ln.strip()
        if s and any(p in s for p in BOLD_PATTERNS) and not s.startswith('**') and len(s) < 120:
            out_lines.append(f'**{s}**')
        else:
            out_lines.append(ln)
    full = '\n'.join(out_lines)
    new_posts.append({
        'id': len(new_posts) + 1,
        'vk_id': pid,
        'slug': meta['slug'],
        'date': meta['date'],
        'type': meta['type'],
        'title': meta['title'],
        'content': short_content(txt),
        'full_content': full,
        'reactions': reacts,
        'comments_count': len(meta.get('comments', [])),
        'shares': 0,
        'has_video': meta['type'] == 'video',
        'video_duration': dur or None,
        'tags': meta['tags'],
        'author': 'БФ «Достижение-Дети»',
        'commenters': meta.get('comments', []),
        'media': build_media(pid, meta['title']),
        'vk_url': f'https://vk.ru/wall-223846998_{pid}',
    })

# ---------- истории детей ----------
stories = [
    {
        'id': 1, 'name': 'Самир Габдуллин', 'age': '13 лет',
        'condition': 'ДЦП и инвалидность',
        'story': 'Самир родился в срок, но из-за родовой травмы пострадал мозг, и как итог — поражение нервной системы. В 2 года ему поставили диагноз ДЦП и инвалидность. С самого рождения семья борется за здоровье Самира: ежедневные занятия и реабилитационные курсы всегда дают свои результаты.',
        'goal': 'Сейчас оплачивается очередной курс реабилитации — без этих процедур Самир не сможет двигаться дальше к мечте ходить самостоятельно.',
        'status': 'Активный сбор средств',
        'post_slug': 'pomoshch-samiru-gabdullinu',
        'image': '/images/post-1334-02.jpg',
        'image_pos': 'top',
        'date_added': '2026-07-10',
    },
    {
        'id': 2, 'name': 'Ваня', 'age': 'не указан',
        'condition': 'Нуждается в реабилитации в Академии развития интеллекта речи',
        'story': 'Наш Ваня очень нуждается в реабилитации в Академии развития интеллекта речи. Обращаемся к каждому неравнодушному, кто хочет поучаствовать в жизни этого ребёнка. В июне Ваня отметил день рождения — мы поздравляем его и верим, что этот год принесёт новые победы.',
        'goal': 'Сбор на реабилитацию в Академии развития интеллекта речи.',
        'status': 'Активный сбор средств',
        'post_slug': 'pomoshch-vane-reabilitatsiya',
        'image': '/images/post-1348-01.jpg',
        'image_pos': 'top',
        'date_added': '2026-07-25',
    },
    {
        'id': 3, 'name': 'Савелий Пенкин', 'age': '15 лет',
        'condition': 'Энцефалопатия, задержка психомоторного развития',
        'story': 'Когда Савелию было 6 месяцев, у него начались приступы эпилепсии, поднялась температура до 40°C. Он оказался в реанимации, врачи боролись за его жизнь. Благодаря вашей помощи оплочен счёт курса реабилитации в ЕВКДС им. Глинки (вт. Евпатория).',
        'goal': 'Сбор 195 200 ₽ на курс реабилитации — ЗАКРЫТ благодаря вашей помощи!',
        'status': 'Сбор закрыт',
        'post_slug': 'sbor-zakryt-saveliy',
        'image': '/images/post-1337-02.jpg',
        'image_pos': 'top',
        'date_added': '2026-07-16',
    },
    {
        'id': 4, 'name': 'Ева', 'age': 'не указан',
        'condition': 'Проходит реабилитацию в Казани',
        'story': 'Наша Ева проходит реабилитацию в Казани. Мы радуемся её новым победам! Огромная благодарность каждому, кто не остаётся в стороне. Самая большая награда — видеть улыбки детей.',
        'goal': 'Поддержка курса реабилитации Евы в Казани.',
        'status': 'Активный сбор средств',
        'post_slug': 'eva-reabilitatsiya-kazan',
        'image': '/images/post-1319-02.jpg',
        'image_pos': 'center 30%',
        'date_added': '2026-06-22',
    },
]

# ---------- СТРАХОВКА ОТ ПОТЕРИ ПОСТОВ ----------
# Посты, добавленные автосинком CI и отсутствующие в статическом META,
# переносим из текущего fund.json без изменений.
meta_ids = {p['vk_id'] for p in new_posts}
carried = [p for p in old['posts'] if p['vk_id'] not in meta_ids]
if carried:
    print('carry-over постов автосинка (нет в META):', [p['vk_id'] for p in carried])
    new_posts.extend(dict(p) for p in carried)

# Хронологический порядок (новые сверху) и перенумерация id
_MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
           'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}


def _date_key(p):
    try:
        _d, m, y = p['date'].split()
        return (int(y), _MONTHS[m], int(_d))
    except Exception:
        return (0, 0, 0)


new_posts.sort(key=_date_key, reverse=True)
for _i, _p in enumerate(new_posts, 1):
    _p['id'] = _i

# Громкая проверка: ни один пост из текущего fund.json не должен исчезнуть
_old_ids = {p['vk_id'] for p in old['posts']}
_new_ids = {p['vk_id'] for p in new_posts}
_lost = _old_ids - _new_ids
assert not _lost, f'ПОТЕРЯ ПОСТОВ при пересборке: {sorted(_lost)}'

# ---------- сборка fund.json ----------
data = dict(old)
data['fund_info'] = dict(old['fund_info'])
data['fund_info']['avatar'] = '/images/fund-avatar.jpg'
data['fund_info']['cover'] = '/images/fund-cover.jpg'
data['stories'] = stories
data['posts'] = new_posts
data['bank_details'] = {
    'fund_name': 'БФ «ДОСТИЖЕНИЕ-ДЕТИ»',
    'inn': '6382076793',
    'kpp': '638201001',
    'bik': '044525593',
    'account': '40703810811950000000',
    'bank': 'АО «АЛЬФА-БАНК»',
    'correspondent_account': '30101810200000000593',
    'payment_purpose': 'Благотворительность',
}
data['stats'] = dict(old.get('stats', {}))
data['parsed_at'] = '2026-08-27'
data['source'] = 'https://vk.ru/dostigenie_deti'

with open(f'{REPO}/src/data/fund.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('posts:', len(new_posts))
print('stories:', len(stories))
for p in new_posts:
    print(f"  [{p['type']:>14}] {p['date']:>16} | {p['title'][:55]:55} | imgs:{len(p['media'])} | ♥{p['reactions']}")
