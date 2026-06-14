from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict

from pnn.translate.config_store import TranslateConfig, load_translate_config
from pnn.translate.provider import translate_configured, translate_text

logger = logging.getLogger(__name__)

# 简单 LRU 缓存，避免分句模式重复请求同一句
_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 200
_lock = threading.RLock()


def _cache_key(
    cfg: TranslateConfig,
    raw: str,
    *,
    from_lang: str | None = None,
    to_lang: str | None = None,
) -> str:
    fl = (from_lang or cfg.from_lang or "auto").strip()
    tl = (to_lang or cfg.to_lang or "zh").strip()
    provider = (cfg.provider or "baidu").strip().lower()
    return f"{provider}:{fl}:{tl}:{raw}"


def _cache_get(keys: list[str]) -> str | None:
    with _lock:
        for key in keys:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
    return None


def _cache_put(keys: list[str], value: str) -> None:
    with _lock:
        for key in keys:
            if key in _CACHE:
                _CACHE.move_to_end(key)
            _CACHE[key] = value
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")


class TranslateService:
    def get_config(self) -> dict:
        cfg = load_translate_config()
        provider = (cfg.provider or "baidu").strip().lower()
        configured = translate_configured(cfg)
        return {
            **{k: v for k, v in cfg.__dict__.items() if k != "secret"},
            "secret": "",
            "configured": configured,
            "provider_label": "必应网页" if provider == "bing" else "百度 API",
        }

    def update_config(self, **kwargs) -> dict:
        from pnn.translate.config_store import save_translate_config

        cfg = load_translate_config()
        for key, value in kwargs.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        save_translate_config(cfg)
        return self.get_config()

    def is_enabled(self) -> bool:
        cfg = load_translate_config()
        return cfg.enabled and translate_configured(cfg)

    def has_credentials(self) -> bool:
        return translate_configured(load_translate_config())

    def _active_reply_language(self) -> str:
        from pnn.characters.reply_lang import active_reply_language

        return active_reply_language()

    def display_translation_for_bubble(self) -> bool:
        """非中文角色且翻译可用时，气泡译成中文。"""
        if not self.has_credentials():
            return False
        if self.is_enabled():
            return True
        from pnn.characters.reply_lang import is_chinese

        return not is_chinese(self._active_reply_language())

    def peek_bubble_translation(self, text: str) -> str | None:
        """气泡用：无需翻译则返回原文；命中缓存则返回译文；否则 None（需异步请求）。"""
        raw = (text or "").strip()
        if not raw:
            return None
        if not self.display_translation_for_bubble():
            return raw
        if self.looks_chinese(raw) and not self.looks_japanese(raw):
            return raw
        cfg = load_translate_config()
        keys = [_cache_key(cfg, raw)]
        if self.looks_japanese(raw):
            keys.append(_cache_key(cfg, raw, from_lang="auto-detect", to_lang="zh-Hans"))
        return _cache_get(keys)

    def to_display_chinese(self, text: str) -> str:
        """气泡/界面用：将模型原文译成中文；失败则回退原文。"""
        raw = (text or "").strip()
        if not raw:
            return ""
        cached = self.peek_bubble_translation(raw)
        if cached is not None:
            return cached
        if not self.display_translation_for_bubble():
            return raw
        cfg = load_translate_config()
        cache_keys = [_cache_key(cfg, raw)]
        cached = _cache_get(cache_keys)
        if cached is not None:
            return cached

        try:
            out = translate_text(raw, cfg)
        except Exception as exc:
            logger.warning("翻译失败，使用原文显示: %s", exc)
            return raw

        _cache_put(cache_keys, out)
        return out

    def looks_chinese(self, text: str) -> bool:
        return bool(_CJK_RE.search(text or ""))

    def looks_japanese(self, text: str) -> bool:
        raw = text or ""
        kana = len(_KANA_RE.findall(raw))
        if kana < 6:
            return False
        han = len(_CJK_RE.findall(raw))
        return kana >= han or kana >= 12

    def to_bubble_chinese(self, text: str) -> str:
        """气泡展示用：日文/混合文案尽量译成简体中文。"""
        raw = (text or "").strip()
        if not raw:
            return ""
        if self.looks_chinese(raw) and not self.looks_japanese(raw):
            return raw
        if not self.has_credentials():
            return raw
        cfg = load_translate_config()
        cache_keys = [_cache_key(cfg, raw, from_lang="auto-detect", to_lang="zh-Hans")]
        cached = _cache_get(cache_keys)
        if cached is not None:
            return cached
        try:
            out = translate_text(
                raw,
                cfg,
                from_lang="auto-detect",
                to_lang="zh-Hans",
            )
        except Exception as exc:
            logger.warning("日文译中失败，气泡使用原文: %s", exc)
            return raw
        _cache_put(cache_keys, out)
        return out

    def for_memory_storage(self, text: str) -> str:
        """记忆库/会话日志入库：日语角色台词译成简体中文。"""
        raw = (text or "").strip()
        if not raw:
            return ""
        if self.looks_chinese(raw) and not self.looks_japanese(raw):
            return raw
        if not self.has_credentials():
            return raw
        return self.to_bubble_chinese(raw)

    def chinese_to_japanese(self, text: str) -> str:
        """识图摘要等中文文案 → 日语朗读稿（日语角色用）。"""
        raw = (text or "").strip()
        if not raw:
            return ""
        cfg = load_translate_config()
        if not translate_configured(cfg):
            logger.warning("未配置翻译，日语角色将用中文合成识图摘要")
            return raw
        cache_keys = [_cache_key(cfg, raw, from_lang="zh-Hans", to_lang="ja")]
        cached = _cache_get(cache_keys)
        if cached is not None:
            return cached
        try:
            out = translate_text(
                raw,
                cfg,
                from_lang="zh-Hans",
                to_lang="ja",
            )
        except Exception as exc:
            logger.warning("识图摘要译日失败，回退中文 TTS: %s", exc)
            return raw
        _cache_put(cache_keys, out)
        return out


translate_service = TranslateService()
