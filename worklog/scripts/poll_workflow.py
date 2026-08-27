#!/usr/bin/env python3
"""Полиление GitHub Actions: ждём завершения прогона VK Sync и качаем логи."""
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

TOKEN = os.environ['GW_TOKEN']
REPO = 'gdp888/bf'
HDR = {'Authorization': f'Bearer {TOKEN}',
       'Accept': 'application/vnd.github+json'}


def api(path):
    req = urllib.request.Request(f'https://api.github.com{path}', headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    print('Жду появления прогона...', flush=True)
    run_id = None
    for _ in range(12):
        runs = api('/repos/gdp888/bf/actions/workflows/vk-sync.yml/runs?per_page=3')
        for run in runs.get('workflow_runs', []):
            if run['event'] in ('workflow_dispatch', 'schedule'):
                run_id = run['id']
                print(f"run {run_id}: {run['status']} / {run['event']}", flush=True)
                break
        if run_id:
            break
        time.sleep(10)

    if not run_id:
        print('RUN_NOT_FOUND')
        return 1

    deadline = time.time() + 25 * 60
    while time.time() < deadline:
        run = api(f'/repos/gdp888/bf/actions/runs/{run_id}')
        if run['status'] == 'completed':
            print(f"ЗАВЕРШЁН: conclusion={run['conclusion']}", flush=True)
            break
        print(f"  ...{run['status']} ({run.get('conclusion')})", flush=True)
        time.sleep(20)

    req = urllib.request.Request(
        f'https://api.github.com/repos/gdp888/bf/actions/runs/{run_id}/logs',
        headers=HDR)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    out_dir = '/home/z/my-project/logs_wfrun'
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(out_dir)
    print('Логи сохранены в', out_dir, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
