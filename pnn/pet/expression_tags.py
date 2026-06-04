"""解析 / 剥离 LLM 输出的【表情:名称】句首标签。"""

from __future__ import annotations

import re

from pnn.pet.emotion import pick_expression
from pnn.pet.tts_chunks import _MIN_CHUNK_LEN, _SENTENCE_END

TAG_PATTERN = re.compile(r"【表情:([^】]+)】")
ACTION_TAG = re.compile(r"【动作:([^】]+)】")
_PAREN_PATTERN = re.compile(r"[（(][^）)]*[）)]")


def strip_expression_tags(text: str) -> str:
    s = _PAREN_PATTERN.sub("", text or "")
    s = TAG_PATTERN.sub("", s)
    s = ACTION_TAG.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def extract_action_name(text: str) -> str | None:
    m = ACTION_TAG.search(text or "")
    return m.group(1).strip() if m else None


def strip_action_tags(text: str) -> str:
    return ACTION_TAG.sub("", text or "").strip()


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
        guessed = pick_expression(clean_sentence, available_expressions=available)
        if guessed in available:
            return guessed
    from pnn.pet.paths import DEFAULT_EXPRESSION

    if DEFAULT_EXPRESSION in available:
        return DEFAULT_EXPRESSION
    return next(iter(available), DEFAULT_EXPRESSION)


def parse_tagged_piece(
    piece: str,
    *,
    available: set[str],
    last_expr: str | None = None,
) -> tuple[str, str, str | None]:
    """从一句原始文本解析 (表情名, 无标签正文, 动作名或 None)。"""
    raw = piece.strip()
    if not raw:
        fb = resolve_expression(last_expr, clean_sentence="", available=available)
        return fb, "", None
    action = extract_action_name(raw)
    m = TAG_PATTERN.match(raw)
    if m:
        name = m.group(1).strip()
        clean = TAG_PATTERN.sub("", raw, count=1)
        clean = ACTION_TAG.sub("", clean)
        clean = _PAREN_PATTERN.sub("", clean).strip()
        expr = resolve_expression(name, clean_sentence=clean, available=available)
        return expr, clean, action
    clean = strip_expression_tags(raw)
    expr = resolve_expression(last_expr, clean_sentence=clean, available=available)
    return expr, clean, action


def pull_tagged_tts_chunks(
    buffer: str,
    spoken_offset: int,
    *,
    available: set[str],
    last_expr: str | None = None,
) -> tuple[list[tuple[str, str, str | None]], int, str | None]:
    """
    从流式原文按句切分，返回 ([(表情, 朗读文本, 动作名或None), ...], 新 offset, 末句表情)。
    offset 按原文 buffer 计（含标签）。
    """
    pending = buffer[spoken_offset:]
    if not pending.strip():
        return [], spoken_offset, last_expr

    chunks: list[tuple[str, str, str | None]] = []
    cursor = 0
    last_end = 0
    expr_carry = last_expr

    while cursor < len(pending):
        ch = pending[cursor]
        if _SENTENCE_END.match(ch):
            piece = pending[last_end : cursor + 1]
            expr, clean, action = parse_tagged_piece(piece, available=available, last_expr=expr_carry)
            if len(clean.strip()) >= _MIN_CHUNK_LEN:
                chunks.append((expr, clean.strip(), action))
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
) -> tuple[tuple[str, str, str | None] | None, int, str | None]:
    tail_raw = buffer[spoken_offset:].strip()
    if not tail_raw:
        return None, len(buffer), last_expr
    expr, clean, action = parse_tagged_piece(tail_raw, available=available, last_expr=last_expr)
    if len(clean.strip()) < _MIN_CHUNK_LEN:
        return None, len(buffer), expr
    return (expr, clean.strip(), action), len(buffer), expr
