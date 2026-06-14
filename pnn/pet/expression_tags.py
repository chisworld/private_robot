"""解析 / 剥离 LLM 输出的【表情:名称】句首标签。"""

from __future__ import annotations

import re

from pnn.pet.emotion import pick_expression
from pnn.pet.tts_chunks import _MIN_CHUNK_LEN, _SENTENCE_END

TAG_PATTERN = re.compile(r"【表情\s*[:：]\s*([^】]+)】")
EMOTION_TAG_PATTERN = re.compile(r"【情绪\s*[:：]\s*([^】]+)】")
ACTION_TAG = re.compile(r"【动作\s*[:：]\s*([^】]+)】")
# 行首裸标签（模型偶发漏括号）
_BARE_EMOTION_LINE = re.compile(
    r"^\s*情绪\s*[:：]\s*[\w\u4e00-\u9fff\-_]+\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# 半角/无括号/残缺的标签（模型偶发）
_EMOTION_LOOSE = re.compile(
    r"(?:【|\[)\s*情绪\s*[:：]\s*[\w\u4e00-\u9fff\-]+\s*(?:】|\])?",
    re.IGNORECASE,
)
_EXPRESSION_LOOSE = re.compile(
    r"(?:【|\[)\s*表情\s*[:：]\s*[^\]】\n]+\s*(?:】|\])?",
    re.IGNORECASE,
)
_ACTION_LOOSE = re.compile(
    r"(?:【|\[)\s*动作\s*[:：]\s*[^\]】\n]+\s*(?:】|\])?",
    re.IGNORECASE,
)
_PAREN_PATTERN = re.compile(r"[（(][^）)]*[）)]")
# 本地 Qwen 等常写「（描写…。」却漏掉右括号
_UNCLOSED_PAREN = re.compile(r"[（(][^）)]*(?=[。！？!?…]|$)")
# 第三人称旁白/动作描写（无对话引号、多描写词）
_NARRATIVE_CUES = (
    "坐在",
    "站在",
    "躺在",
    "听到",
    "眼眸",
    "嘴角",
    "微微",
    "缓缓",
    "轻轻",
    "手里",
    "注视",
    "拿起",
    "沙发",
    "手柄",
    "抬头",
    "低头",
    "转身",
)
# 本地 Qwen 等偶发省略前缀：【:soft】【:skirt_side】
_BARE_COLON_TAG = re.compile(r"【\s*:\s*([^】]+)\s*】")
# 本地 Qwen 偶发合并写法：【high:default:default】或【soft:Black】
_COMBINED_COLON_TAG = re.compile(r"【\s*([^】\s][^】]*?)\s*】")
_DEFAULT_EMOTION_IDS = frozenset(
    {"angry", "asking", "high", "ironic", "soft", "normal1", "normal2"}
)


def _expand_combined_colon_tag(inner: str, *, available: set[str], emotion_ids: set[str]) -> str:
    parts = [p.strip() for p in inner.split(":") if p.strip()]
    if len(parts) < 2:
        return f"【{inner}】"
    expr_lower = {e.lower(): e for e in available}
    out: list[str] = []
    idx = 0
    first = parts[0].lower()
    if first in emotion_ids:
        out.append(f"【情绪:{first}】")
        idx = 1
    for part in parts[idx:]:
        low = part.lower()
        if part in available:
            out.append(f"【表情:{part}】")
        elif low in expr_lower:
            out.append(f"【表情:{expr_lower[low]}】")
        elif low in emotion_ids:
            out.append(f"【情绪:{low}】")
        else:
            out.append(f"【:{part}】")
    return "".join(out)


def normalize_pet_output_tags(
    text: str,
    *,
    available: set[str] | None = None,
    emotion_ids: set[str] | None = None,
) -> str:
    """将【:name】/【high:default】等写法还原为标准【情绪/表情:…】。"""
    s = text or ""
    if not s or "【" not in s:
        return s
    emo = {e.lower() for e in (emotion_ids or _DEFAULT_EMOTION_IDS)}
    expr = available or frozenset()
    expr_lower = {e.lower(): e for e in expr}

    def _repl_combined(m: re.Match[str]) -> str:
        inner = (m.group(1) or "").strip()
        if not inner or inner.startswith(":"):
            return m.group(0)
        if "情绪" in inner or "表情" in inner or "动作" in inner:
            return m.group(0)
        if ":" not in inner:
            return m.group(0)
        return _expand_combined_colon_tag(inner, available=expr, emotion_ids=emo)

    s = _COMBINED_COLON_TAG.sub(_repl_combined, s)

    def _repl(m: re.Match[str]) -> str:
        name = (m.group(1) or "").strip()
        if not name:
            return m.group(0)
        low = name.lower()
        if low in emo:
            return f"【情绪:{low}】"
        if name in expr:
            return f"【表情:{name}】"
        if low in expr_lower:
            return f"【表情:{expr_lower[low]}】"
        return m.group(0)

    return _BARE_COLON_TAG.sub(_repl, s)


def _looks_like_stage_direction(text: str) -> bool:
    """整句是否为动作/神态描写（非角色台词）。"""
    t = (text or "").strip()
    if not t or len(t) < 4:
        return False
    if t.startswith("（") or t.startswith("("):
        return True
    if re.search(r"[「『]", t):
        return False
    hits = sum(1 for k in _NARRATIVE_CUES if k in t)
    return hits >= 2


def strip_stage_directions(text: str) -> str:
    """去掉括号内/未闭合的动作神态描写。"""
    s = text or ""
    s = _PAREN_PATTERN.sub("", s)
    s = _UNCLOSED_PAREN.sub("", s)
    s = re.sub(r"^[，、。！？…\s]+", "", s)
    return s.strip()


def normalize_dialogue_quotes(text: str) -> str:
    """清理 LLM 偶发的「」书名号式包裹，避免 TTS 读出孤立引号。"""
    s = (text or "").strip()
    if not s:
        return s
    s = re.sub(r"[」』]\s*[「『]", " ", s)
    s = re.sub(r"^[「『]+", "", s)
    s = re.sub(r"[」』]+$", "", s)
    s = re.sub(r"[「『]+", "", s)
    s = re.sub(r"[」』]+", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def strip_expression_tags(text: str) -> str:
    s = normalize_pet_output_tags(text or "")
    for pat in (
        TAG_PATTERN,
        EMOTION_TAG_PATTERN,
        ACTION_TAG,
        _EMOTION_LOOSE,
        _EXPRESSION_LOOSE,
        _ACTION_LOOSE,
    ):
        s = pat.sub("", s)
    s = strip_stage_directions(s)
    s = _BARE_EMOTION_LINE.sub("", s)
    s = re.sub(r"【[^】]{0,32}】", "", s)
    s = re.sub(r"\[[^\]]{0,32}\]", "", s)
    s = normalize_dialogue_quotes(s)
    return re.sub(r"\s{2,}", " ", s).strip()


def extract_action_name(text: str) -> str | None:
    m = ACTION_TAG.search(text or "")
    return m.group(1).strip() if m else None


def strip_action_tags(text: str) -> str:
    return ACTION_TAG.sub("", text or "").strip()


def extract_emotion_tag_name(text: str) -> str | None:
    m = EMOTION_TAG_PATTERN.search(text or "")
    return m.group(1).strip() if m else None


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
    last_emotion_tag: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    """解析 (Live2D 表情名, 无标签正文, 动作名, AI 情绪标签 id)。"""
    raw = normalize_pet_output_tags(
        piece.strip(),
        available=available,
    )
    if not raw:
        fb = resolve_expression(last_expr, clean_sentence="", available=available)
        return fb, "", None, last_emotion_tag
    action = extract_action_name(raw)
    emotion_tag = extract_emotion_tag_name(raw) or last_emotion_tag
    working = EMOTION_TAG_PATTERN.sub("", raw, count=1).strip() if emotion_tag and extract_emotion_tag_name(raw) else raw
    m = TAG_PATTERN.match(working)
    if m:
        name = m.group(1).strip()
        clean = TAG_PATTERN.sub("", working, count=1)
        clean = EMOTION_TAG_PATTERN.sub("", clean)
        clean = ACTION_TAG.sub("", clean)
        clean = strip_stage_directions(clean).strip()
        if _looks_like_stage_direction(clean):
            clean = ""
        expr = resolve_expression(name, clean_sentence=clean, available=available)
        return expr, clean, action, emotion_tag
    clean = strip_expression_tags(working)
    if _looks_like_stage_direction(clean):
        clean = ""
    expr = resolve_expression(last_expr, clean_sentence=clean, available=available)
    return expr, clean, action, emotion_tag


def pull_tagged_tts_chunks(
    buffer: str,
    spoken_offset: int,
    *,
    available: set[str],
    last_expr: str | None = None,
    last_emotion_tag: str | None = None,
) -> tuple[list[tuple[str, str, str | None, str | None]], int, str | None, str | None]:
    """
    从流式原文按句切分，返回 ([(表情, 朗读文本, 动作, 情绪标签), ...], offset, 末句表情, 末句情绪标签)。
    """
    pending = buffer[spoken_offset:]
    if not pending.strip():
        return [], spoken_offset, last_expr, last_emotion_tag

    chunks: list[tuple[str, str, str | None, str | None]] = []
    cursor = 0
    last_end = 0
    expr_carry = last_expr
    emotion_carry = last_emotion_tag

    while cursor < len(pending):
        ch = pending[cursor]
        if _SENTENCE_END.match(ch):
            piece = pending[last_end : cursor + 1]
            expr, clean, action, emotion_tag = parse_tagged_piece(
                piece,
                available=available,
                last_expr=expr_carry,
                last_emotion_tag=emotion_carry,
            )
            if len(clean.strip()) >= _MIN_CHUNK_LEN:
                chunks.append((expr, clean.strip(), action, emotion_tag))
                expr_carry = expr
                if emotion_tag:
                    emotion_carry = emotion_tag
            last_end = cursor + 1
        cursor += 1

    return chunks, spoken_offset + last_end, expr_carry, emotion_carry


def pull_final_tagged_chunk(
    buffer: str,
    spoken_offset: int,
    *,
    available: set[str],
    last_expr: str | None = None,
    last_emotion_tag: str | None = None,
) -> tuple[tuple[str, str, str | None, str | None] | None, int, str | None, str | None]:
    tail_raw = buffer[spoken_offset:].strip()
    if not tail_raw:
        return None, len(buffer), last_expr, last_emotion_tag
    expr, clean, action, emotion_tag = parse_tagged_piece(
        tail_raw,
        available=available,
        last_expr=last_expr,
        last_emotion_tag=last_emotion_tag,
    )
    if len(clean.strip()) < _MIN_CHUNK_LEN:
        return None, len(buffer), expr, emotion_tag
    return (expr, clean.strip(), action, emotion_tag), len(buffer), expr, emotion_tag
