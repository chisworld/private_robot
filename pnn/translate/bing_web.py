"""必应（Bing）网页版翻译：调用 cn.bing.com/ttranslatev3，无需 AppID。"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_BING_HOST = "https://cn.bing.com"
_TRANSLATOR_PAGE = f"{_BING_HOST}/translator?mkt=zh-CN"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 百度/旧配置码 → 必应 API 语言码
_LANG_TO_BING: dict[str, str] = {
    "auto": "auto-detect",
    "auto-detect": "auto-detect",
    "jp": "ja",
    "ja": "ja",
    "jpn": "ja",
    "zh": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-hans": "zh-Hans",
    "zh-hant": "zh-Hant",
    "en": "en",
    "kor": "ko",
    "ko": "ko",
}


def normalize_bing_lang(code: str, *, default: str = "auto-detect") -> str:
    raw = (code or "").strip()
    if not raw:
        return default
    key = raw.lower().replace("_", "-")
    return _LANG_TO_BING.get(key, raw)


@dataclass
class _BingAuth:
    ig: str
    key: str
    token: str
    iid: str
    fetched_at: float


_lock = threading.RLock()
_session = None
_auth: _BingAuth | None = None
_req_seq = 0


def _requests():
    import requests

    return requests


def _session_get():
    global _session
    if _session is None:
        sess = _requests().Session()
        sess.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
            }
        )
        _session = sess
    return _session


def _parse_auth(html: str) -> _BingAuth:
    ig_m = re.search(r'IG:"([^"]+)"', html)
    params_m = re.search(r"params_AbusePreventionHelper\s*=\s*\[(.*?)\];", html)
    iid_m = re.search(r'id="rich_tta"[^>]*data-iid="([^"]+)"', html)
    if not iid_m:
        iid_m = re.search(r'data-iid="(translator\.[^"]+)"', html)
    if not ig_m or not params_m:
        raise RuntimeError("必应翻译页缺少 IG/token 参数（可能被墙或页面改版）")
    abuse = params_m.group(1).replace('"', "").split(",")
    if len(abuse) < 2:
        raise RuntimeError("必应翻译 token 解析失败")
    iid = iid_m.group(1).strip() if iid_m else "translator.5023"
    return _BingAuth(
        ig=ig_m.group(1).strip(),
        key=abuse[0].strip(),
        token=abuse[1].strip(),
        iid=iid,
        fetched_at=time.monotonic(),
    )


def _refresh_auth(*, force: bool = False) -> _BingAuth:
    global _auth
    with _lock:
        if (
            not force
            and _auth is not None
            and time.monotonic() - _auth.fetched_at < 3600.0
        ):
            return _auth
        sess = _session_get()
        resp = sess.get(_TRANSLATOR_PAGE, timeout=15.0)
        resp.raise_for_status()
        _auth = _parse_auth(resp.text)
        return _auth


def _next_iid(base: str) -> str:
    global _req_seq
    _req_seq += 1
    if re.search(r"\.\d+$", base):
        return f"{base}.{_req_seq}"
    return f"{base}.{_req_seq}"


def _extract_text(payload: Any) -> str:
    if isinstance(payload, list) and payload:
        payload = payload[0]
    if not isinstance(payload, dict):
        return ""
    trans = payload.get("translations")
    if isinstance(trans, list) and trans:
        first = trans[0]
        if isinstance(first, dict):
            return str(first.get("text") or "").strip()
    return ""


def bing_web_translate(
    text: str,
    *,
    from_lang: str = "auto-detect",
    to_lang: str = "zh-Hans",
    timeout: float = 15.0,
) -> str:
    """自动检测源语言 → 目标语；失败抛异常。"""
    q = (text or "").strip()
    if not q:
        return ""
    src = normalize_bing_lang(from_lang, default="auto-detect")
    dst = normalize_bing_lang(to_lang, default="zh-Hans")
    last_err = "必应翻译无响应"
    for attempt in range(2):
        auth = _refresh_auth(force=attempt > 0)
        iid = _next_iid(auth.iid)
        url = (
            f"{_BING_HOST}/ttranslatev3?isVertical=1"
            f"&IG={auth.ig}&IID={iid}"
        )
        data = {
            "fromLang": src,
            "to": dst,
            "text": q,
            "token": auth.token,
            "key": auth.key,
            "tryFetchingGenderDebiasedTranslations": "true",
        }
        sess = _session_get()
        try:
            resp = sess.post(
                url,
                data=data,
                headers={
                    "Referer": f"{_BING_HOST}/translator",
                    "Origin": _BING_HOST,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            body = (resp.text or "").strip()
            if not body:
                last_err = "必应翻译返回空（token 可能过期）"
                continue
            parsed = json.loads(body)
            out = _extract_text(parsed)
            if out:
                return out
            last_err = f"必应翻译 JSON 无译文: {body[:120]}"
        except json.JSONDecodeError as exc:
            last_err = f"必应翻译 JSON 解析失败: {exc}"
        except Exception as exc:
            last_err = str(exc)
            logger.debug("必应翻译 attempt %s 失败: %s", attempt + 1, exc)
    raise RuntimeError(last_err)
