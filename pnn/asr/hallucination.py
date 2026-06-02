from __future__ import annotations

import re

import numpy as np

# Whisper 在静音/噪声时常见的幻听短语（尤其中文训练集字幕水印）
_HALLUCINATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"字幕",
        r"索兰娅",
        r"谢谢观看",
        r"感谢观看",
        r"感谢收看",
        r"请不吝点赞",
        r"订阅.*转发",
        r"打赏.*支持",
        r"^[\s，。！？、…\.]+$",
        r"^(.)\1{3,}$",  # 重复单字
    )
)

# 过短且无中文/英文实质内容的碎片
_MIN_MEANINGFUL_LEN = 2


def audio_rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def audio_loud_enough(audio: np.ndarray, min_rms: float) -> bool:
    return audio_rms(audio) >= min_rms


def is_likely_hallucination(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    if len(cleaned) < _MIN_MEANINGFUL_LEN:
        return True
    return any(pattern.search(cleaned) for pattern in _HALLUCINATION_PATTERNS)


def filter_transcript(text: str, *, no_speech_prob: float | None = None) -> str:
    """过滤幻听文本，返回空字符串表示应丢弃。"""
    if no_speech_prob is not None and no_speech_prob > 0.55:
        return ""
    if is_likely_hallucination(text):
        return ""
    return text.strip()
