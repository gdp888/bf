#!/usr/bin/env python3
"""Локальная отладка CI-синка: что видит Playwright на странице группы."""
import json
import time
from playwright.sync_api import sync_playwright

GROUP_URL = 'https://vk.ru/dostigenie_deti'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

COLLECT_JS = """
(() => {
  const out = {};
  document.querySelectorAll('[data-post-id]').forEach(art => {
    const id = art.getAttribute('data-post-id');
    if (!new RegExp('^-%GID%_\\\\d+$').test(id)) return;
    const c = art.querySelector('.wall_post_cont');
    const wall = art.querySelector('.wall_text');
    const txt = ((wall || c || {}).innerText || '').trim();
    if (!out[id] || (out[id].txt || '').length < txt.length) {
      out[id] = {id: id, txt: txt.slice(0, 200), reacts: ''};
    }
  });
  return out;
})()
""".replace('%GID%', '223846998')

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled'])
    ctx = browser.new_context(user_agent=UA,
                              viewport={'width': 1366, 'height': 900},
                              locale='ru-RU', timezone_id='Europe/Moscow')
    page = ctx.new_page()
    page.goto(GROUP_URL, wait_until='domcontentloaded', timeout=60000)
    try:
        page.wait_for_selector('[data-post-id]', timeout=30000)
        print('selector [data-post-id] найден')
    except Exception:
        print('selector НЕ найден за 30с')
    time.sleep(2)

    dbg = page.evaluate("""
(() => ({
  url: location.href,
  title: document.title,
  anyPostIds: document.querySelectorAll('[data-post-id]').length,
  sampleIds: [...document.querySelectorAll('[data-post-id]')]
              .slice(0, 6).map(e => e.getAttribute('data-post-id')),
  bodySnippet: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 300),
  wallTextCount: document.querySelectorAll('.wall_text').length,
  wallContCount: document.querySelectorAll('.wall_post_cont').length,
}))
""")
    print(json.dumps(dbg, ensure_ascii=False, indent=1))

    batch = page.evaluate(COLLECT_JS)
    print('COLLECT_JS дал:', len(batch), 'постов')
    for k, v in list(batch.items())[:5]:
        print(' ', k, repr(v['txt'][:80]))

    # скроллим как в CI
    total = {}
    for i in range(8):
        page.evaluate('window.scrollBy(0, 900)')
        time.sleep(1.1)
        total.update(page.evaluate(COLLECT_JS))
        print(f'после скролла {i+1}: {len(total)}')
    page.screenshot(path='/home/z/my-project/pw_debug.png')
    browser.close()
