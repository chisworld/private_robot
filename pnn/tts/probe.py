from __future__ import annotations

import os
import time

import requests

_ALIVE_CODES = frozenset({200, 404, 405})
_DEFAULT_TTL = 5.0
_probe_cache: dict[str, tuple[float, bool]] = {}


def _cache_ttl() -> float:
    raw = os.getenv("TTS_PROBE_CACHE_TTL", str(_DEFAULT_TTL)).strip()
    try:
        return max(0.5, float(raw))
    except ValueError:
        return _DEFAULT_TTL


def invalidate_probe_cache(base_url: str | None = None) -> None:
    if base_url is None:
        _probe_cache.clear()
        return
    _probe_cache.pop(base_url.rstrip("/"), None)


def probe_http_server(base_url: str, *, timeout: float = 2.0) -> bool:
    """检测 TTS HTTP 是否已监听。旧版 GPT-SoVITS 根路径 404 也视为已启动。"""
    url = base_url.rstrip("/") + "/"
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code in _ALIVE_CODES
    except requests.RequestException:
        return False


def probe_http_server_cached(
    base_url: str,
    *,
    timeout: float = 2.0,
    ttl: float | None = None,
) -> bool:
    """带短时缓存的探测，避免 config/health 频繁打 9880。"""
    key = base_url.rstrip("/")
    wait = _cache_ttl() if ttl is None else max(0.5, ttl)
    now = time.monotonic()
    cached = _probe_cache.get(key)
    if cached is not None and now - cached[0] < wait:
        return cached[1]
    alive = probe_http_server(base_url, timeout=timeout)
    _probe_cache[key] = (now, alive)
    return alive
