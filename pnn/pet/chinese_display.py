"""【中文】展示后处理：去掉模型漏写的假名/日词。"""

from __future__ import annotations

import re

_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff]+")

# 模型在【中文】块里常漏写的日词 → 简体中文（长词优先）
_JA_ZH_GLOSSARY: tuple[tuple[str, str], ...] = (
    ("おちんちん", "鸡鸡"),
    ("オチンチン", "鸡鸡"),
    ("ちんちん", "鸡鸡"),
    ("チンチン", "鸡鸡"),
    ("ちんぽ", "肉棒"),
    ("チンポ", "肉棒"),
    ("おまんこ", "小穴"),
    ("オマンコ", "小穴"),
    ("まんこ", "小穴"),
    ("マンコ", "小穴"),
    ("おっぱい", "胸部"),
    ("オッパイ", "胸部"),
    ("お兄ちゃん", "哥哥"),
    ("オニイチャン", "哥哥"),
    ("兄ちゃん", "哥哥"),
    ("にいさん", "哥哥"),
    ("アナル", "后面"),
    ("あなル", "后面"),
    ("アナル", "后面"),
    ("セックス", "做爱"),
    ("えっち", "色色的事"),
    ("エッチ", "色色的事"),
    ("イク", "去了"),
    ("いく", "去了"),
)


def polish_chinese_display(text: str) -> str:
    """界面/终端/记忆用的中文：替换常见日词；仍含假名时尝试译中。"""
    s = (text or "").strip()
    if not s:
        return s
    for ja, zh in _JA_ZH_GLOSSARY:
        if ja in s:
            s = s.replace(ja, zh)
    if not _KANA.search(s):
        return s
    try:
        from pnn.translate.service import translate_service

        if translate_service.has_credentials():
            out = translate_service.to_bubble_chinese(s)
            if (out or "").strip() and not _KANA.search(out):
                return out.strip()
    except Exception:
        pass
    return s
