"""TTS 文本清理：GPT-SoVITS 在中文 Windows 下常用 GBK，部分 Unicode 会导致合成失败。"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# 已知 GBK 无法编码、且有常见替代品的字符
_GBK_REPLACEMENTS: dict[str, str] = {
    "\u301c": "\uff5e",  # 波ダッシュ (U+301C) → 全角～ (U+FF5E，GBK 可编码)
    "\u2015": "\u2014",  # 水平线 → 破折号
    "\u2212": "-",  # 数学减号 → ASCII 连字符
}


def _normalize_lang(lang: str | None) -> str:
    return (lang or "zh").strip().lower().replace("_", "-")


def sanitize_for_gbk_tts(text: str, lang: str | None = None) -> str:
    """将 TTS 文本转为 GBK 可编码形式，避免 GPT-SoVITS 返回 400。

    非中文语言（ja/en/ko 等）仅做已知字符替换，不剔除 Unicode。
    """
    if not text:
        return text

    for src, dst in _GBK_REPLACEMENTS.items():
        text = text.replace(src, dst)

    code = _normalize_lang(lang)
    if code not in ("zh", "yue"):
        return text

    out: list[str] = []
    for ch in text:
        try:
            ch.encode("gbk")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass

        norm = unicodedata.normalize("NFKC", ch)
        if norm != ch:
            try:
                norm.encode("gbk")
                out.append(norm)
                continue
            except UnicodeEncodeError:
                pass

        logger.debug("TTS 文本移除 GBK 无法编码字符 U+%04X", ord(ch))

    return "".join(out)


_SPLIT_BOUNDARY = re.compile(r"(?<=[。！？!?…、，,;；\n])")


def split_for_tts(text: str, *, max_chars: int = 120) -> list[str]:
    """长文本按标点切分为多段，避免单次 GPT-SoVITS 请求过长失败。"""
    raw = (text or "").strip()
    if not raw:
        return []
    if len(raw) <= max_chars:
        return [raw]

    parts = [p for p in _SPLIT_BOUNDARY.split(raw) if p.strip()]
    if not parts:
        parts = [raw]

    chunks: list[str] = []
    buf = ""
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        candidate = f"{buf}{piece}" if buf else piece
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(piece) <= max_chars:
            buf = piece
            continue
        for i in range(0, len(piece), max_chars):
            chunks.append(piece[i : i + max_chars])
    if buf:
        chunks.append(buf)
    return chunks or [raw[:max_chars]]
