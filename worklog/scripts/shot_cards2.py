#!/usr/bin/env python3
"""Проверка кадрирования фото в карточках: головы не должны срезаться."""
import functools
import http.server
import os
import socketserver
import threading

DIST = '/home/z/my-project/repo-bf/dist'
OUT = '/home/z/my-project/shots'
os.makedirs(OUT, exist_ok=True)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(('127.0.0.1', 4399), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:4399'

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # --- desktop ---
    pg = browser.new_page(viewport={'width': 1280, 'height': 1400})
    pg.goto(BASE + '/', wait_until='networkidle')
    pg.locator('#sbory').scroll_into_view_if_needed()
    pg.evaluate('window.scrollBy(0, -60)')
    pg.wait_for_timeout(600)
    pg.screenshot(path=f'{OUT}/cards-objectpos-desktop.png')

    # computed object-position каждого фото в карточках
    imgs = pg.locator('#sbory article img')
    n = imgs.count()
    for i in range(n):
        el = imgs.nth(i)
        src = el.get_attribute('src')
        op = el.evaluate("e => getComputedStyle(e).objectPosition")
        print(f'card {i}: {src} -> object-position: {op}')

    # --- mobile ---
    pg_m = browser.new_page(viewport={'width': 390, 'height': 3000})
    pg_m.goto(BASE + '/', wait_until='networkidle')
    pg_m.locator('#sbory').scroll_into_view_if_needed()
    pg_m.wait_for_timeout(600)
    pg_m.screenshot(path=f'{OUT}/cards-objectpos-mobile.png')

    # --- /stories ---
    pg_s = browser.new_page(viewport={'width': 1280, 'height': 1400})
    pg_s.goto(BASE + '/stories/', wait_until='networkidle')
    pg_s.evaluate('window.scrollTo(0, 700)')
    pg_s.wait_for_timeout(600)
    pg_s.screenshot(path=f'{OUT}/stories-objectpos.png')

    browser.close()
httpd.shutdown()
print('done')
