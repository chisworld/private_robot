"""统一翻译入口：百度 API / 必应网页版。"""

from __future__ import annotations

from pnn.translate.baidu import baidu_translate
from pnn.translate.bing_web import bing_web_translate, normalize_bing_lang
from pnn.translate.config_store import TranslateConfig


def translate_text(
    text: str,
    cfg: TranslateConfig,
    *,
    from_lang: str | None = None,
    to_lang: str | None = None,
    timeout: float = 15.0,
) -> str:
    src = from_lang or cfg.from_lang
    dst = to_lang or cfg.to_lang
    provider = (cfg.provider or "baidu").strip().lower()
    if provider == "bing":
        return bing_web_translate(
            text,
            from_lang=normalize_bing_lang(src, default="auto-detect"),
            to_lang=normalize_bing_lang(dst, default="zh-Hans"),
            timeout=timeout,
        )
    return baidu_translate(
        text,
        app_id=cfg.app_id,
        secret=cfg.secret,
        from_lang=src or "auto",
        to_lang=dst or "zh",
        timeout=timeout,
    )


def translate_configured(cfg: TranslateConfig) -> bool:
    provider = (cfg.provider or "baidu").strip().lower()
    if provider == "bing":
        return True
    return bool(cfg.app_id.strip() and cfg.secret.strip())
