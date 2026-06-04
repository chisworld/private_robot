from __future__ import annotations

import logging
import re
import threading

from pnn.translate.baidu import baidu_translate
from pnn.translate.config_store import TranslateConfig, load_translate_config

logger = logging.getLogger(__name__)

# 简单缓存，避免分句模式重复请求同一句
_CACHE: dict[str, str] = {}
_CACHE_MAX = 200
_lock = threading.RLock()

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class TranslateService:
    def get_config(self) -> dict:
        cfg = load_translate_config()
        return {
            **{k: v for k, v in cfg.__dict__.items() if k != "secret"},
            "secret": "",
            "configured": bool(cfg.app_id.strip() and cfg.secret.strip()),
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
        return cfg.enabled and bool(cfg.app_id.strip() and cfg.secret.strip())

    def has_credentials(self) -> bool:
        cfg = load_translate_config()
        return bool(cfg.app_id.strip() and cfg.secret.strip())

    def _active_reply_language(self) -> str:
        from pnn.characters.reply_lang import active_reply_language

        return active_reply_language()

    def display_translation_for_bubble(self) -> bool:
        """非中文角色且已配置百度密钥时，气泡译成中文。"""
        if not self.has_credentials():
            return False
        if self.is_enabled():
            return True
        from pnn.characters.reply_lang import is_chinese

        return not is_chinese(self._active_reply_language())

    def to_display_chinese(self, text: str) -> str:
        """气泡/界面用：将模型原文译成中文；失败则回退原文。"""
        raw = (text or "").strip()
        if not raw:
            return ""
        if not self.display_translation_for_bubble():
            return raw
        cfg = load_translate_config()

        cache_key = f"{cfg.from_lang}:{cfg.to_lang}:{raw}"
        with _lock:
            if cache_key in _CACHE:
                return _CACHE[cache_key]

        try:
            out = baidu_translate(
                raw,
                app_id=cfg.app_id,
                secret=cfg.secret,
                from_lang=cfg.from_lang,
                to_lang=cfg.to_lang,
            )
        except Exception as exc:
            logger.warning("翻译失败，使用原文显示: %s", exc)
            return raw

        with _lock:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[cache_key] = out
        return out

    def looks_chinese(self, text: str) -> bool:
        return bool(_CJK_RE.search(text or ""))

    def chinese_to_japanese(self, text: str) -> str:
        """识图摘要等中文文案 → 日语朗读稿（日语角色用）。"""
        raw = (text or "").strip()
        if not raw:
            return ""
        cfg = load_translate_config()
        if not cfg.app_id.strip() or not cfg.secret.strip():
            logger.warning("未配置百度翻译，日语角色将用中文合成识图摘要")
            return raw
        cache_key = f"zh:jp:{raw}"
        with _lock:
            if cache_key in _CACHE:
                return _CACHE[cache_key]
        try:
            out = baidu_translate(
                raw,
                app_id=cfg.app_id,
                secret=cfg.secret,
                from_lang="zh",
                to_lang="jp",
            )
        except Exception as exc:
            logger.warning("识图摘要译日失败，回退中文 TTS: %s", exc)
            return raw
        with _lock:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[cache_key] = out
        return out


translate_service = TranslateService()
