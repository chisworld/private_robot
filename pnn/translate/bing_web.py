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

_BING_HOSTS = (
    "https://www.bing.com",
    "https://cn.bing.com",
)
_MAX_AUTH_ATTEMPTS = 3
_MAX_TRANSLATE_ATTEMPTS = 3
# 即使页面 TTL 写 1h，也定期刷新 token，避免长时间运行后失效
_AUTH_CACHE_MAX_SECONDS = 600.0
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
    host: str
    ig: str
    key: str
    token: str
    iid: str
    fetched_at: float
    cache_seconds: float = _AUTH_CACHE_MAX_SECONDS


_lock = threading.RLock()
_session = None
_auth: _BingAuth | None = None
_req_seq = 0


def _requests():
    import requests

    return requests


def _is_transient_net_error(exc: BaseException) -> bool:
    try:
        import requests

        if isinstance(
            exc,
            (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ),
        ):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "ssl",
            "unexpected_eof",
            "connection aborted",
            "connection reset",
            "timed out",
        )
    )


def _reset_session() -> None:
    """SSL/连接异常后丢弃旧 Session，避免复用坏连接。"""
    global _session, _auth
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
    _session = None
    _auth = None


def _session_get():
    global _session
    if _session is None:
        requests = _requests()
        sess = requests.Session()
        sess.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
            }
        )
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            retry = Retry(
                total=2,
                connect=2,
                read=2,
                backoff_factor=0.4,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
            )
            adapter = HTTPAdapter(max_retries=retry)
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
        except Exception:
            logger.debug("必应 Session Retry 适配器未启用", exc_info=True)
        _session = sess
    return _session


def _parse_auth(html: str, *, host: str) -> _BingAuth:
    ig_m = re.search(r'IG:"([^"]+)"', html)
    params_m = re.search(
        r'params_AbusePreventionHelper\s*=\s*\[(\d+),\s*"([^"]+)",\s*(\d+)\s*\];',
        html,
    )
    iid_m = re.search(r'id="rich_tta"[^>]*data-iid="([^"]+)"', html)
    if not iid_m:
        iid_m = re.search(r'data-iid="(translator\.[^"]+)"', html)
    if not ig_m or not params_m:
        raise RuntimeError("必应翻译页缺少 IG/token 参数（可能被墙或页面改版）")
    ttl_ms = int(params_m.group(3))
    cache_seconds = min(max(ttl_ms / 1000.0 * 0.85, 60.0), _AUTH_CACHE_MAX_SECONDS)
    iid = iid_m.group(1).strip() if iid_m else "translator.5023"
    return _BingAuth(
        host=host.rstrip("/"),
        ig=ig_m.group(1).strip(),
        key=params_m.group(1).strip(),
        token=params_m.group(2).strip(),
        iid=iid,
        fetched_at=time.monotonic(),
        cache_seconds=cache_seconds,
    )


def _fetch_auth_from_host(host: str, sess) -> _BingAuth:
    page = f"{host.rstrip('/')}/translator?mkt=zh-CN"
    resp = sess.get(page, timeout=15.0)
    resp.raise_for_status()
    return _parse_auth(resp.text, host=host.rstrip("/"))


def _refresh_auth(*, force: bool = False, prefer_host: str | None = None) -> _BingAuth:
    global _auth
    with _lock:
        if (
            not force
            and _auth is not None
            and time.monotonic() - _auth.fetched_at < _auth.cache_seconds
            and (not prefer_host or _auth.host.rstrip("/") == prefer_host.rstrip("/"))
        ):
            return _auth
        hosts = list(_BING_HOSTS)
        if prefer_host:
            prefer = prefer_host.rstrip("/")
            hosts.sort(key=lambda h: 0 if h.rstrip("/") == prefer else 1)
        last_err = "必应翻译页拉取失败"
        for attempt in range(_MAX_AUTH_ATTEMPTS):
            if attempt > 0 or force:
                _reset_session()
                time.sleep(0.35 * attempt)
            sess = _session_get()
            for host in hosts:
                try:
                    _auth = _fetch_auth_from_host(host, sess)
                    return _auth
                except Exception as exc:
                    last_err = str(exc)
                    logger.debug(
                        "必应 auth 拉取失败 host=%s attempt=%s: %s",
                        host,
                        attempt + 1,
                        exc,
                    )
                    if _is_transient_net_error(exc):
                        _reset_session()
                        sess = _session_get()
        raise RuntimeError(last_err)


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


def _post_translate(
    auth: _BingAuth,
    *,
    text: str,
    from_lang: str,
    to_lang: str,
    timeout: float,
) -> tuple[str, str | None]:
    """返回 (译文, 错误说明)；成功时错误为 None。"""
    host = auth.host or _BING_HOSTS[0]
    iid = _next_iid(auth.iid)
    url = f"{host.rstrip('/')}/ttranslatev3?isVertical=1&IG={auth.ig}&IID={iid}"
    data = {
        "fromLang": from_lang,
        "to": to_lang,
        "text": text,
        "token": auth.token,
        "key": auth.key,
        "tryFetchingGenderDebiasedTranslations": "true",
    }
    sess = _session_get()
    resp = sess.post(
        url,
        data=data,
        headers={
            "Referer": f"{host.rstrip('/')}/translator",
            "Origin": host.rstrip("/"),
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    body = (resp.text or "").strip()
    if not body:
        return "", f"必应翻译返回空（host={host}，token 可能过期或节点不可用）"
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        return "", f"必应翻译 JSON 解析失败: {exc}"
    out = _extract_text(parsed)
    if out:
        return out, None
    return "", f"必应翻译 JSON 无译文: {body[:120]}"


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
    for attempt in range(_MAX_TRANSLATE_ATTEMPTS):
        host_order = list(_BING_HOSTS)
        if attempt > 0:
            host_order.reverse()
        for host in host_order:
            try:
                auth = _refresh_auth(force=attempt > 0, prefer_host=host)
            except Exception as exc:
                last_err = str(exc)
                if _is_transient_net_error(exc):
                    _reset_session()
                continue
            try:
                out, err = _post_translate(
                    auth,
                    text=q,
                    from_lang=src,
                    to_lang=dst,
                    timeout=timeout,
                )
            except Exception as exc:
                last_err = str(exc)
                logger.debug(
                    "必应翻译 host=%s attempt=%s 失败: %s",
                    host,
                    attempt + 1,
                    exc,
                )
                if _is_transient_net_error(exc):
                    _reset_session()
                time.sleep(0.25 * attempt)
                continue
            if out:
                return out
            last_err = err or last_err
            logger.debug(
                "必应翻译 host=%s attempt=%s 空响应: %s",
                host,
                attempt + 1,
                last_err,
            )
            _reset_session()
    raise RuntimeError(last_err)
