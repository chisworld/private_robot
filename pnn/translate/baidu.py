from __future__ import annotations

import hashlib
import logging
import random
import time
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

BAIDU_API = "https://fanyi-api.baidu.com/api/trans/vip/translate"


def baidu_translate(
    text: str,
    *,
    app_id: str,
    secret: str,
    from_lang: str = "jp",
    to_lang: str = "zh",
    timeout: float = 12.0,
) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    if not app_id.strip() or not secret.strip():
        raise ValueError("未配置百度翻译 AppID / Secret")

    salt = str(random.randint(32768, 65536))
    sign_raw = f"{app_id}{q}{salt}{secret}"
    sign = hashlib.md5(sign_raw.encode("utf-8")).hexdigest()
    params = {
        "q": q,
        "from": from_lang or "auto",
        "to": to_lang or "zh",
        "appid": app_id,
        "salt": salt,
        "sign": sign,
    }
    resp = requests.get(f"{BAIDU_API}?{urlencode(params)}", timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error_code" in data:
        raise RuntimeError(
            f"百度翻译错误 {data.get('error_code')}: {data.get('error_msg', '')}"
        )
    items = data.get("trans_result") or []
    if not items:
        return q
    parts = [str(it.get("dst", "")).strip() for it in items if it.get("dst")]
    return "\n".join(p for p in parts if p) or q
