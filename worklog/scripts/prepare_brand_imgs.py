#!/usr/bin/env python3
"""Готовим бренд-ассеты и фото Евы к публикации на сайте (resize + web-качество)."""
import os
from PIL import Image

SRC = '/home/z/my-project/brand_dl'
DST = '/home/z/my-project/repo-bf/public/images'


def process(src_name, dst_name, max_side=None, quality=85):
    im = Image.open(os.path.join(SRC, src_name)).convert('RGB')
    if max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    out = os.path.join(DST, dst_name)
    im.save(out, 'JPEG', quality=quality, optimize=True, progressive=True)
    print(f'{dst_name}: {im.size[0]}x{im.size[1]} {os.path.getsize(out)/1024:.0f}Kb')


# Логотип 1440 -> 512, заменяем старый аватар 240px
process('fund-logo.jpg', 'fund-avatar.jpg', max_side=512, quality=88)
# Обложка: оставляем 1822x728, чуть пережимаем
process('fund-cover.jpg', 'fund-cover.jpg', quality=86)
# Фото Евы: 1280x1707 -> 1200 по длинной стороне
process('eva-1319-01.jpg', 'post-1319-01.jpg', max_side=1200, quality=84)
process('eva-1319-02.jpg', 'post-1319-02.jpg', max_side=1200, quality=84)
print('done')
