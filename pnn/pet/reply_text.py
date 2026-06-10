"""角色回复文案：气泡展示 vs TTS 合成（语言、去记忆元叙述）。"""

from __future__ import annotations

import re

from pnn.characters.reply_lang import active_reply_language, normalize_reply_language

# 句首「根据记忆 / 我想起」类前缀
_MEMORY_RECALL_PREFIX = re.compile(
    r"^(?:"
    r"(?:根据|按照|从|按)?(?:长期|之前|以前的)?记忆(?:里|中|显示|来看)?[,，、：:\s]*"
    r"|(?:我|咱)?(?:想起|回忆起|记起来|记得)(?:了|起来|啦)?[,，、：:\s]*"
    r"|长期记忆(?:显示|里|中)?[,，、：:\s]*"
    r"|(?:思い出(?:した|しました|します)|記憶(?:による|から|には)(?:と)?|"
    r"覚えて(?:います|る|おります))[,、：:\s]*"
    r")+",
    re.IGNORECASE,
)

_MEMORY_RECALL_BRACKET = re.compile(
    r"【[^】]*(?:记忆|記憶|回忆|思い出|长期)[^】]*】"
)

# 整句丢弃：气泡不展示「我在回忆 / 记忆库 / 记性」类句子，也不展示记忆提取摘要口吻
_MEMORY_META_SENTENCE = re.compile(
    r"(?:"
    r"记忆(?:里|中|库)?"
    r"|(?:都|还|已)?(?:有)?(?:好好)?记(?:着|住|录|下来)"
    r"|记性(?:好|不好|差|如何)"
    r"|(?:长期|短期)?记忆"
    r"|(?:想起|回忆|回想)(?:了|起来|过)?"
    r"|記憶(?:の中|にある|して)"
    r"|(?:覚|おぼ)えて(?:い|お)?(?:る|ます|り)"
    r")",
    re.IGNORECASE,
)

# 记忆写入摘要口吻（如「主人询问…塞拉记得…并提到是…告诉她的」）
_MEMORY_ADMIN_SUMMARY = re.compile(
    r"(?:询问|问到|提到是|告诉(?:她|他|我|塞拉)|是否记得).*(?:记得|记忆|妹妹叫|名字)",
    re.IGNORECASE,
)

_JA_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_SENTENCE_SPLIT = re.compile(r"([。！？!?…]+|~+|～+)")


def _is_memory_meta_sentence(sentence: str) -> bool:
    t = sentence.strip()
    if not t:
        return False
    if _MEMORY_ADMIN_SUMMARY.search(t):
        return True
    if _MEMORY_META_SENTENCE.search(t):
        return True
    if "想想看" in t and re.search(r"记忆|想起|记着|记性", t):
        return True
    return False


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text)
    if not parts:
        return []
    out: list[str] = []
    i = 0
    while i < len(parts):
        body = parts[i].strip()
        punct = parts[i + 1] if i + 1 < len(parts) else ""
        if body:
            out.append((body + punct).strip())
        i += 2 if punct else 1
    if not out and text.strip():
        return [text.strip()]
    return out


def strip_memory_recall_phrases(text: str) -> str:
    """去掉回忆/记忆元叙述，气泡只留自然对话内容。"""
    s = (text or "").strip()
    if not s:
        return ""
    s = _MEMORY_RECALL_BRACKET.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = _MEMORY_RECALL_PREFIX.sub("", s.strip())
    kept = [seg for seg in _split_sentences(s) if not _is_memory_meta_sentence(seg)]
    s = "".join(kept).strip()
    s = re.sub(r"^[，、。！？…\s]+", "", s)
    s = re.sub(r"[，、]{2,}", "，", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _looks_japanese(text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return False
    if _JA_KANA.search(body):
        return True
    try:
        from pnn.translate.service import translate_service

        return not translate_service.looks_chinese(body)
    except Exception:
        return False


def _load_tts_address_pair() -> tuple[str, str]:
    """角色包配置的称呼：气泡中文 / 语音日文。"""
    try:
        from pnn.characters.service import character_pack_service
        from pnn.characters.pack import load_pack

        character_pack_service.ensure_migrated()
        pack = load_pack(character_pack_service.get_active_id())
        if pack is None:
            return "", ""
        zh = (pack.time_greetings.address_zh or "").strip()
        ja = (pack.time_greetings.address_ja or "").strip()
        if not zh and "哥哥" in (pack.character_prompt or ""):
            zh = "哥哥"
        if not ja and zh == "哥哥":
            ja = "お兄ちゃん"
        return zh, ja
    except Exception:
        return "", ""


# 模型偶发写进台词的中文/罗马音称呼 → 日语 TTS 可读形式
_CN_ADDRESS_ALIASES: tuple[tuple[str, str], ...] = (
    ("欧尼酱", "お兄ちゃん"),
    ("欧尼桑", "お兄ちゃん"),
    ("尼桑", "兄さん"),
    ("尼酱", "お兄ちゃん"),
    ("老哥", "兄さん"),
    ("大哥", "兄さん"),
)


def apply_address_terms_for_tts(text: str, lang: str | None = None) -> str:
    """日语 TTS 前：把中文称呼换成角色包配置的日语读法（如 哥哥→お兄ちゃん）。"""
    raw = (text or "").strip()
    if not raw:
        return raw
    code = normalize_reply_language(lang or active_reply_language())
    if code != "ja":
        return raw

    address_zh, address_ja = _load_tts_address_pair()
    out = raw
    if address_zh and address_ja and address_zh != address_ja:
        out = out.replace(address_zh, address_ja)
    ja_default = address_ja or "お兄ちゃん"
    for cn, ja in _CN_ADDRESS_ALIASES:
        if cn in out:
            out = out.replace(cn, ja_default if ja == "お兄ちゃん" else ja)
    return out


def tts_text_for_reply(text: str, lang: str | None = None) -> str:
    """TTS 用文本：日语角色若混入中文则先译成日语再合成。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    code = normalize_reply_language(lang or active_reply_language())
    if code != "ja":
        return raw
    if _looks_japanese(raw):
        body = raw
    else:
        try:
            from pnn.translate.service import translate_service

            body = translate_service.chinese_to_japanese(raw) or raw
        except Exception:
            body = raw
    return apply_address_terms_for_tts(body, code)


def bubble_text_for_reply(text: str) -> str:
    """气泡展示：剥离表情/情绪/动作标签，并去记忆元叙述。"""
    from pnn.pet.expression_tags import strip_expression_tags

    s = strip_memory_recall_phrases(strip_expression_tags(text))
    if not s:
        return ""
    kept: list[str] = []
    for line in s.splitlines():
        row = line.strip()
        if not row:
            continue
        if strip_expression_tags(row):
            kept.append(line)
    if kept:
        s = "\n".join(kept)
    return s.strip()


def terminal_text_for_reply(text: str) -> str:
    """终端 [pet-ai]/[pet-tts] 展示：与气泡同规则，并可选译成中文。"""
    body = bubble_text_for_reply(text)
    if not body:
        return ""
    try:
        from pnn.translate.service import translate_service

        if not translate_service.display_translation_for_bubble():
            return body
        cached = translate_service.peek_bubble_translation(body)
        if cached is not None:
            return cached
        out = translate_service.to_display_chinese(body)
        if not (out or "").strip():
            return body
        if out.strip() == body.strip() and _JA_KANA.search(body):
            return body
        return out.strip()
    except Exception:
        return body
