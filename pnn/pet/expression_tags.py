"""解析 / 剥离 LLM 输出的【表情:名称】句首标签。"""

from __future__ import annotations

import re

from pnn.pet.emotion import pick_expression
from pnn.pet.paths import DEFAULT_EXPRESSION
from pnn.pet.tts_chunks import _MIN_CHUNK_LEN, _SENTENCE_END

TAG_PATTERN = re.compile(r"【表情:([^】]+)】")


def strip_expression_tags(text: str) -> str:
    return TAG_PATTERN.sub("", text or "").strip()


def resolve_expression(
    name: str | None,
    *,
    clean_sentence: str,
    available: set[str],
) -> str:
    n = (name or "").strip()
    if n and n in available:
        return n
    if clean_sentence.strip():
        guessed = pick_expression(clean_sentence)
        if guessed in available:
            return guessed
    if DEFAULT_EXPRESSION in available:
        return DEFAULT_EXPRESSION
    return next(iter(available), DEFAULT_EXPRESSION)


def parse_tagged_piece(
    piece: str,
    *,
    available: set[str],
    last_expr: str | None = None,
) -> tuple[str, str]:
    """从一句原始文本解析 (表情名, 无标签正文)。"""
    raw = piece.strip()
    if not raw:
        fb = resolve_expression(last_expr, clean_sentence="", available=available)
        return fb, ""
    m = TAG_PATTERN.match(raw)
    if m:
        name = m.group(1).strip()
        clean = TAG_PATTERN.sub("", raw, count=1).strip()
        expr = resolve_expression(name, clean_sentence=clean, available=available)
        return expr, clean
    clean = strip_expression_tags(raw)
    expr = resolve_expression(last_expr, clean_sentence=clean, available=available)
    return expr, clean


def pull_tagged_tts_chunks(
    buffer: str,
    spoken_offset: int,
    *,
    available: set[str],
    last_expr: str | None = None,
) -> tuple[list[tuple[str, str]], int, str | None]:
    """
    从流式原文按句切分，返回 ([(表情, 朗读文本), ...], 新 offset, 末句表情)。
    offset 按原文 buffer 计（含标签）。
    """
    pending = buffer[spoken_offset:]
    if not pending.strip():
        return [], spoken_offset, last_expr

    chunks: list[tuple[str, str]] = []
    cursor = 0
    last_end = 0
    expr_carry = last_expr

    while cursor < len(pending):
        ch = pending[cursor]
        if _SENTENCE_END.match(ch):
            piece = pending[last_end : cursor + 1]
            expr, clean = parse_tagged_piece(piece, available=available, last_expr=expr_carry)
            if len(clean.strip()) >= _MIN_CHUNK_LEN:
                chunks.append((expr, clean.strip()))
                expr_carry = expr
            last_end = cursor + 1
        cursor += 1

    return chunks, spoken_offset + last_end, expr_carry


def pull_final_tagged_chunk(
    buffer: str,
    spoken_offset: int,
    *,
    available: set[str],
    last_expr: str | None = None,
) -> tuple[tuple[str, str] | None, int, str | None]:
    tail_raw = buffer[spoken_offset:].strip()
    if not tail_raw:
        return None, len(buffer), last_expr
    expr, clean = parse_tagged_piece(tail_raw, available=available, last_expr=last_expr)
    if len(clean.strip()) < _MIN_CHUNK_LEN:
        return None, len(buffer), expr
    return (expr, clean.strip()), len(buffer), expr
