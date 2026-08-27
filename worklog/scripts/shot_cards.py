#!/usr/bin/env python3
"""Проверка: карточка без кнопок + hover-состояние, шапка без VK."""
import functools
import http.server
import os
import socketserver
import threading

DIST = '/home/z/my-project/repo-bf/dist'
OUT = '/home/z/my-project/shots'
os.makedirs(OUT, exist_ok=True)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
httpd = socketserver.TCPServer(('127.0.0.1', 4399), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:4399'

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    pg = browser.new_page(viewport={'width': 1280, 'height': 1100})
    pg.goto(BASE + '/', wait_until='networkidle')
    pg.evaluate('window.scrollTo(0, 950)')
    pg.wait_for_timeout(500)
    pg.screenshot(path=f'{OUT}/cards-plain.png')
    # hover на карточку Евы (третья)
    card = pg.locator('article').nth(2)
    card.hover()
    pg.wait_for_timeout(500)
    pg.screenshot(path=f'{OUT}/cards-hover.png')
    # проверка ссылки карточки
    href = card.locator('a').first.get_attribute('href')
    print('card link:', href)
    # клик ведёт на историю?
    card.click()
    pg.wait_for_load_state('networkidle')
    print('after click url:', pg.url)
    # шапка: сколько ссылок ВК на странице верхнего уровня
    pg.goto(BASE + '/', wait_until='networkidle')
    vk_in_header = pg.locator('header a[href*="vk.ru"]').count()
    vk_in_footer = pg.locator('footer a[href*="vk.ru"]').count()
    print('vk in header:', vk_in_header, '| vk in footer:', vk_in_footer)
    browser.close()
httpd.shutdown()
print('done')
