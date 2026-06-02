from __future__ import annotations

_converter = None


def to_simplified_chinese(text: str, language: str | None = None) -> str:
    """将识别结果统一为简体中文。"""
    if not text:
        return text
    if language not in (None, "", "zh"):
        return text

    global _converter
    try:
        if _converter is None:
            from opencc import OpenCC

            _converter = OpenCC("t2s")
        return _converter.convert(text)
    except Exception:
        return text
