#!/usr/bin/env python3
"""Общие хелпы для agent-browser (повторяем паттерн из vk_fetch_missed.py)."""
import json
import subprocess


def ab(cmd, timeout=90):
    r = subprocess.run(['agent-browser'] + cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or '').strip()


def ab_eval(js, timeout=90):
    out = ab(['eval', js], timeout)
    if out.startswith('"') and out.endswith('"'):
        out = json.loads(out)
    return out
