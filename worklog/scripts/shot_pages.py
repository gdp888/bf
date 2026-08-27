#!/usr/bin/env python3
"""Скриншоты собранного сайта: hero с обложкой, блок сборов (Ева!), истории, пост Евы."""
import http.server
import os
import socketserver
import threading
import functools

DIST = '/home/z/my-project/repo-bf/dist'
OUT = '/home/z/my-project/shots'
os.makedirs(OUT, exist_ok=True)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
httpd = socketserver.TCPServer(('127.0.0.1', 4399), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print('server on :4399')

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:4399'
targets = [
    ('home-top', '/', 0, 1280, 900),
    ('home-sbory', '/', 950, 1280, 1100),
    ('home-mobile-sbory', '/', 900, 390, 1400),
    ('stories', '/stories', 0, 1280, 1000),
    ('post-eva', '/posts/eva-reabilitatsiya-kazan', 0, 1280, 1000),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, path, scroll, w, h in targets:
        pg = browser.new_page(viewport={'width': w, 'height': h})
        pg.goto(BASE + path, wait_until='networkidle')
        if scroll:
            pg.evaluate(f'window.scrollTo(0, {scroll})')
            pg.wait_for_timeout(600)
        pg.wait_for_timeout(400)
        pg.screenshot(path=f'{OUT}/{name}.png')
        print('shot:', name)
        pg.close()
    browser.close()
httpd.shutdown()
print('done')
