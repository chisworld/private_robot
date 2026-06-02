#!/usr/bin/env python3
"""本地 API 冒烟测试（不启动完整 GPT-SoVITS 合成）。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"


def get(path: str, timeout: float = 8.0) -> tuple[float, dict | str, int]:
    t0 = time.perf_counter()
    r = requests.get(f"{BASE}{path}", timeout=timeout)
    elapsed = time.perf_counter() - t0
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    return elapsed, body, r.status_code


def post(path: str, payload: dict | None = None, timeout: float = 15.0) -> tuple[float, dict | str, int]:
    t0 = time.perf_counter()
    r = requests.post(f"{BASE}{path}", json=payload or {}, timeout=timeout)
    elapsed = time.perf_counter() - t0
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    return elapsed, body, r.status_code


def main() -> int:
    failures = 0
    checks = [
        ("GET", "/api/health", None, 5.0),
        ("GET", "/api/tts/health", None, 10.0),
        ("GET", "/api/memory/config", None, 10.0),
        ("GET", "/api/chat/config", None, 10.0),
        ("GET", "/api/tts/config", None, 15.0),
    ]
    print("== PNN Garden smoke test ==")
    for method, path, body, limit in checks:
        try:
            if method == "GET":
                elapsed, data, code = get(path, timeout=limit)
            else:
                elapsed, data, code = post(path, body, timeout=limit)
            slow = " SLOW" if elapsed > 2.0 else ""
            ok = code == 200
            if not ok:
                failures += 1
            print(f"[{'OK' if ok else 'FAIL'}]{slow} {method} {path} {elapsed:.2f}s code={code}")
            if isinstance(data, dict):
                preview = {k: data[k] for k in list(data)[:6]}
                print(f"       {json.dumps(preview, ensure_ascii=False)[:120]}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {method} {path}: {exc}")

    print("\n== TTS preload (non-blocking) ==")
    try:
        elapsed, data, code = post("/api/tts/preload", timeout=20.0)
        print(f"[{'OK' if code == 200 else 'FAIL'}] POST /api/tts/preload {elapsed:.2f}s {data}")
    except Exception as exc:
        failures += 1
        print(f"[FAIL] preload: {exc}")

    print("\n== runtime paths ==")
    sys.path.insert(0, str(ROOT))
    from pnn.core.paths import CACHE_DIR, PROJECT_ROOT
    from pnn.core.runtime_files import RUNTIME_TMP_DIR

    print(f"  PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"  CACHE_DIR exists: {CACHE_DIR.is_dir()}")
    print(f"  RUNTIME_TMP_DIR: {RUNTIME_TMP_DIR}")
    audio = CACHE_DIR / "audio"
    if audio.is_dir():
        wavs = list(audio.glob("*.wav"))
        print(f"  cache/audio wav count: {len(wavs)}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
