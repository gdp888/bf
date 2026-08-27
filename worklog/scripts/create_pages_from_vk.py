#!/usr/bin/env python3
"""
Конвертирует экспортированные посты ВК в отдельные страницы для сайта
Каждый пост становится markdown-файлом с frontmatter
"""

import json
import os
from datetime import datetime

# Пути
EXPORT_FILE = "/workspace/worklog/data/fund_export.json"
OUTPUT_DIR = "/workspace/worklog/posts"

# Создаём директорию для страниц
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Загружаем данные
with open(EXPORT_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"📦 Загружено {data['total_posts']} постов из ВК")
print(f"📁 Сохраняем в: {OUTPUT_DIR}")

# Шаблоны типов постов
TYPE_LABELS = {
    "post": "Новость",
    "event": "Мероприятие",
    "call_to_action": "Призыв к действию",
    "pinned": "Закреплённый пост",
    "video": "Видео"
}

created_count = 0

for post in data['posts_summary']:
    # Формируем slug
    slug = post['slug']
    
    # Определяем тип
    post_type = post.get('type', 'post')
    type_label = TYPE_LABELS.get(post_type, 'Новость')
    
    # Создаём markdown-файл
    filename = f"{slug}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    # Frontmatter для Astro
    frontmatter = f"""---
title: "{post['title']}"
date: "{post['date']}"
type: "{post_type}"
typeLabel: "{type_label}"
vkId: "{post['vk_id']}"
mediaCount: {post.get('media_count', 0)}
reactions: {post.get('reactions', 0)}
source: "VK"
sourceUrl: "https://vk.ru/dostigenie_deti?post={post['vk_id']}"
---

"""
    
    # Основной контент (заголовок + дата)
    content = f"""# {post['title']}

**Дата публикации:** {post['date']}  
**Тип:** {type_label}  
**Источник:** [ВКонтакте](https://vk.ru/dostigenie_deti?post={post['vk_id']})

"""
    
    # Добавляем информацию о медиа и реакциях
    if post.get('media_count', 0) > 0:
        content += f"\n📸 **Медиа:** {post['media_count']} фото/видео\n"
    
    if post.get('reactions', 0) > 0:
        content += f"❤️ **Реакции:** {post['reactions']}\n"
    
    content += "\n---\n\n*Пост импортирован из ВКонтакте*\n"
    
    # Записываем файл
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(frontmatter + content)
    
    created_count += 1
    print(f"✅ Создан: {filename} ({post['title'][:40]}...)")

print(f"\n🎉 Готово! Создано {created_count} страниц в {OUTPUT_DIR}")
print(f"📂 Теперь можно закоммитить их в Git и запушить на GitHub")
