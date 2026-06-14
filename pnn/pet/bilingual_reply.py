"""解析 AI 双语回复：角色语言（TTS）+ 【中文】块（界面/记忆）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CHINESE_MARKER = re.compile(r"【中文\s*[:：]?\s*】", re.IGNORECASE)
# 兼容模型偶发写法
_CHINESE_MARKER_ALT = re.compile(r"【(?:译文|中译|简体)\s*[:：]?\s*】", re.IGNORECASE)


@dataclass(frozen=True)
class BilingualReply:
    raw: str
    speech: str
    chinese: str
    has_chinese_block: bool


def _find_chinese_marker(text: str) -> re.Match[str] | None:
    for pat in (_CHINESE_MARKER, _CHINESE_MARKER_ALT):
        m = pat.search(text)
        if m:
            return m
    return None


def split_bilingual_reply(text: str) -> BilingualReply:
    raw = (text or "").strip()
    if not raw:
        return BilingualReply("", "", "", False)
    m = _find_chinese_marker(raw)
    if not m:
        return BilingualReply(raw, raw, "", False)
    speech = raw[: m.start()].strip()
    chinese = raw[m.end() :].strip()
    return BilingualReply(raw, speech, chinese, True)


def has_chinese_marker(text: str) -> bool:
    return _find_chinese_marker(text or "") is not None


def speech_buffer_for_tts(text: str) -> str:
    """TTS 分句用：去掉 【中文】 及其后内容。"""
    bi = split_bilingual_reply(text)
    return bi.speech if bi.has_chinese_block else bi.raw


def speech_text_for_history(text: str) -> str:
    """写入对话 history 供下轮 LLM：仅保留朗读语种正文。"""
    return speech_buffer_for_tts(text)


def chinese_text_from_reply(text: str) -> str:
    """提取模型自带的【中文】块（不含标签行）。"""
    bi = split_bilingual_reply(text)
    return (bi.chinese or "").strip()


def _normalize_speech_key(text: str) -> str:
    from pnn.pet.expression_tags import strip_expression_tags

    s = strip_expression_tags(text or "").strip()
    s = re.sub(r"\s+", "", s)
    return s


def build_bilingual_sentence_pairs(raw: str) -> list[tuple[str, str]]:
    """朗读句与【中文】句按序配对（句数不一致时尽量对齐）。"""
    from pnn.pet.reply_text import split_reply_sentences

    bi = split_bilingual_reply(raw)
    if not bi.has_chinese_block:
        return []
    speech_sents = split_reply_sentences(bi.speech)
    zh_sents = split_reply_sentences(bi.chinese)
    if not speech_sents:
        return []
    if not zh_sents:
        return [(sp, "") for sp in speech_sents]
    pairs: list[tuple[str, str]] = []
    for i, sp in enumerate(speech_sents):
        zh = zh_sents[i] if i < len(zh_sents) else zh_sents[-1]
        pairs.append((sp, zh))
    return pairs


def chinese_display_for_segment(
    raw: str,
    speech_piece: str,
    *,
    seg_index: int = 0,
) -> str:
    """终端/TTS 分句对应的中文（优先【中文】块按句对齐）。"""
    from pnn.pet.reply_text import split_reply_sentences, terminal_text_for_reply

    bi = split_bilingual_reply(raw)
    if bi.has_chinese_block and (bi.chinese or "").strip():
        from pnn.pet.chinese_display import polish_chinese_display

        zh_sents = split_reply_sentences(bi.chinese)
        picked = ""
        if seg_index < len(zh_sents):
            picked = zh_sents[seg_index].strip()
        else:
            speech_sents = split_reply_sentences(bi.speech)
            key = _normalize_speech_key(speech_piece)
            for i, sp in enumerate(speech_sents):
                sp_key = _normalize_speech_key(sp)
                if not key or not sp_key:
                    continue
                if key == sp_key or key in sp_key or sp_key in key:
                    if i < len(zh_sents):
                        picked = zh_sents[i].strip()
                    break
            if not picked and len(zh_sents) == 1:
                picked = zh_sents[0].strip()
        if picked:
            return polish_chinese_display(picked)
        return ""
    return terminal_text_for_reply(speech_piece) or speech_piece.strip()


def bilingual_reply_enabled() -> bool:
    """非中文角色：要求模型附带【中文】块。"""
    try:
        from pnn.characters.reply_lang import active_reply_language, is_chinese

        return not is_chinese(active_reply_language())
    except Exception:
        return True


def llm_bilingual_output_rule(lang: str | None = None) -> str:
    """注入 LLM 的双语输出规则（中文角色返回空）。"""
    try:
        from pnn.characters.reply_lang import is_chinese, is_japanese, normalize_reply_language

        code = normalize_reply_language(lang or "")
    except Exception:
        code = "ja"
    if is_chinese(code):
        return ""
    if is_japanese(code):
        speech_lang = "日语（日本語）"
    else:
        speech_lang = "角色设定语言"
    return (
        "【双语输出 — 必须遵守】\n"
        f"1. 先写用于语音合成的{speech_lang}台词（可含句首【情绪/表情/动作】标签）；"
        "该段只含朗读内容，禁止夹杂简体中文句子。\n"
        "2. 另起一行写【中文】，其后接与上一段同义的简体中文（界面显示与记忆库用，"
        "不要朗读、不要重复标签）；【中文】内按句分行，句数与朗读段一致。\n"
        "3. 【中文】块内必须全部使用简体中文字符，禁止假名（ひらがな/カタカナ/ローマ字）；"
        "身体部位、性相关词也必须写成中文（如「鸡鸡」「小穴」「肉棒」），"
        "禁止写おちんちん、まんこ等日语词。\n"
        "4. 若只有一句，也须两行：日语句 + 【中文】中文句。"
    )
