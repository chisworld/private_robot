from __future__ import annotations

import requests

_ALIVE_CODES = frozenset({200, 404, 405})


def probe_http_server(base_url: str, *, timeout: float = 2.0) -> bool:
    """检测 TTS HTTP 是否已监听。旧版 GPT-SoVITS 根路径 404 也视为已启动。"""
    url = base_url.rstrip("/") + "/"
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code in _ALIVE_CODES
    except requests.RequestException:
        return False
