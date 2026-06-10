"""待办标题润色：按角色设定将解析出的事项写成列表展示文案。"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from pnn.llm.client import DeepSeekClient
from pnn.llm.config_store import load_llm_config

logger = logging.getLogger(__name__)

_TITLE_MAX_LEN = 32
_PROMPT_SNIPPET_LEN = 240
_STRIP_QUOTES = re.compile(r'^[\s"\'「」『』《》【】]+|[\s"\'「」『』《》【】]+$')


def _guess_address_zh(prompt: str) -> str:
    """从人设摘要推断对用户的称呼（未配置 time_greetings 时）。"""
    body = prompt or ""
    for pat in (
        r'习惯称呼[^为]*?为[「""\u201c]([^」""\u201d，,]+)[」""\u201d]',
        r'称呼[^为]*?为[「""\u201c]([^」""\u201d，,]+)[」""\u201d]',
    ):
        m = re.search(pat, body)
        if m:
            addr = (m.group(1) or "").strip()
            if addr and len(addr) <= 8:
                return addr
    return ""


def _load_character_context(character_id: str) -> tuple[str, str, str]:
    """返回 (角色名, 对用户的称呼, 人设摘要)。"""
    cid = (character_id or "").strip()
    if not cid:
        return "", "", ""
    try:
        from pnn.characters.pack import load_pack

        pack = load_pack(cid)
        if pack is None:
            return cid, "", ""
        name = (pack.name or pack.id or cid).strip()
        prompt = re.sub(r"\s+", " ", (pack.character_prompt or "").strip())
        if len(prompt) > _PROMPT_SNIPPET_LEN:
            prompt = prompt[:_PROMPT_SNIPPET_LEN] + "…"
        addr = (pack.time_greetings.address_zh or "").strip()
        if not addr:
            addr = _guess_address_zh(pack.character_prompt or "")
        return name, addr, prompt
    except Exception as exc:
        logger.debug("加载角色包失败（待办润色）: %s", exc)
        return cid, "", ""


def _normalize_title(text: str) -> str:
    t = _STRIP_QUOTES.sub("", (text or "").strip())
    t = re.sub(r"[\r\n]+", "", t)
    t = re.sub(r"[。！!？?；;，,]+$", "", t).strip()
    if len(t) > _TITLE_MAX_LEN:
        t = t[:_TITLE_MAX_LEN].rstrip()
    return t


def fallback_reminder_title(
    raw_title: str,
    *,
    address_zh: str = "",
    user_text: str = "",
) -> str:
    """无 LLM 时按角色称呼生成模板标题。"""
    raw = (raw_title or "").strip() or "约定事项"
    addr = (address_zh or "").strip() or "你"
    body = user_text or ""

    if re.search(r"起床|起来|叫醒", body) or raw == "起床":
        return _normalize_title(f"到点叫醒{addr}")
    if re.search(r"睡觉|睡吧|入睡|就寝|熄灯", body) or raw in {"睡觉", "一起睡觉"}:
        if raw.startswith("一起") or re.search(r"我们|一起|咱俩", body):
            return _normalize_title(f"和{addr}约定好一起睡觉")
        return _normalize_title(f"和{addr}约定好睡觉")
    if re.search(r"洗澡|泡澡|沐浴|搓背|淋浴", body) or raw in {"洗澡", "一起洗澡"}:
        if raw.startswith("一起") or re.search(r"我们|一起|咱俩", body):
            return _normalize_title(f"和{addr}约定好一起洗澡")
        return _normalize_title(f"和{addr}约定好洗澡")
    if re.search(r"吃药|取药", body) or raw == "吃药":
        return _normalize_title(f"到点提醒{addr}吃药")
    if re.search(r"开会|会议", body) or raw == "开会":
        return _normalize_title(f"到点提醒{addr}开会")
    if re.search(r"喝水", body) or raw == "喝水":
        return _normalize_title(f"到点提醒{addr}喝水")
    if re.search(r"锻炼|健身|跑步|瑜伽|游泳|爬山", body):
        return _normalize_title(f"和{addr}约定好{raw or '锻炼'}")
    if re.search(r"收菜|打卡|签到|上线|做日常", body):
        return _normalize_title(f"到点提醒{addr}{raw}")
    if re.search(r"交作业|交论文|交稿|答辩", body):
        return _normalize_title(f"到点提醒{addr}{raw}")
    if re.search(r"取快递|寄快递|倒垃圾|遛狗|喂猫", body):
        return _normalize_title(f"到点提醒{addr}{raw}")
    if re.search(r"接孩子|送孩子|赶飞机|赶车", body):
        return _normalize_title(f"到点提醒{addr}{raw}")
    if re.search(r"直播|开播|下播", body):
        return _normalize_title(f"到点提醒{addr}{raw or '直播'}")
    if re.search(r"看电影|看剧|追剧|剧本杀|KTV", body):
        return _normalize_title(f"和{addr}约定好{raw or '活动'}")
    if re.search(r"体检|复查|挂号|看医生", body):
        return _normalize_title(f"到点提醒{addr}{raw or '看医生'}")
    if re.search(r"提醒|叫我|记得", body):
        return _normalize_title(f"到点提醒{addr}{raw}")
    if re.search(r"吃|饭|餐|一起|用膳", body) or raw in {
        "吃饭",
        "午饭",
        "晚饭",
        "早餐",
        "晚餐",
    }:
        food = raw
        if food.startswith("吃"):
            food = food[1:].strip() or raw
        if food.startswith("一起"):
            return _normalize_title(f"和{addr}约定好{food}")
        return _normalize_title(f"和{addr}约定好一起吃{food}")
    return _normalize_title(f"和{addr}约定好{raw}")


def _build_polish_system(
    *,
    character_name: str,
    address_zh: str,
    prompt_snippet: str,
) -> str:
    name = character_name or "角色"
    addr = address_zh or "用户"
    lines = [
        f"你是{name}的日程助手。根据用户原话与已解析的事项，写一条简短的中文待办标题（显示在待办列表）。",
        f"角色对用户的称呼是「{addr}」（若原话未出现其他称呼，请用此称呼）。",
        "要求：",
        "1. 一条完整短语，20字以内为佳，最多32字。",
        f"2. 体现约定内容，例如："
        f"吃饭→「和{addr}约定好一起吃黄焖鸡米饭」；"
        f"起床→「到点叫醒{addr}」；"
        f"睡觉→「和{addr}约定好一起睡觉」；"
        f"洗澡/洗漱→「和{addr}约定好一起洗澡」；"
        f"提醒类→「到点提醒{addr}吃药/喝水/收菜/上线/交作业」；"
        f"出行→「到点提醒{addr}赶飞机/接孩子/取快递」；"
        f"娱乐→「和{addr}约定好一起玩鸣潮/看电影/剧本杀」；"
        f"工作学习→「到点提醒{addr}开会/交论文/刷题」；"
        f"生活→「到点提醒{addr}倒垃圾/遛狗/晾衣服」。",
        "3. 语气可带一点角色性格，但不要写成台词或过长对话。",
        "4. 不要写日期、时间、括号（列表会单独显示时间）。",
        "5. 只输出标题正文，不要引号、不要解释。",
    ]
    if prompt_snippet:
        lines.append(f"角色设定摘要：{prompt_snippet}")
    return "\n".join(lines)


def polish_reminder_title(
    user_text: str,
    raw_title: str,
    scheduled_start: datetime,
    *,
    character_id: str = "",
    character_name: str = "",
) -> str:
    """LLM 润色待办标题；失败或未配置 Key 时退回模板。"""
    raw = (raw_title or "").strip()
    if not raw:
        return raw

    cname, addr, prompt = _load_character_context(character_id)
    if (character_name or "").strip():
        cname = character_name.strip()
    fallback = fallback_reminder_title(raw, address_zh=addr, user_text=user_text)

    cfg = load_llm_config()
    if not cfg.api_key.strip():
        return fallback

    when = scheduled_start.strftime("%Y-%m-%d %H:%M")
    user = (
        f"用户原话：{user_text.strip()}\n"
        f"已解析事项：{raw}\n"
        f"约定时间：{when}\n"
        "请输出待办列表标题。"
    )
    client = DeepSeekClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        timeout=30.0,
    )
    try:
        result = client.chat(
            [
                {
                    "role": "system",
                    "content": _build_polish_system(
                        character_name=cname,
                        address_zh=addr,
                        prompt_snippet=prompt,
                    ),
                },
                {"role": "user", "content": user},
            ],
            temperature=0.35,
            max_tokens=80,
        )
        polished = _normalize_title(result.get("content") or "")
        if polished and len(polished) >= 4:
            return polished
    except Exception as exc:
        logger.warning("待办标题润色失败，使用模板: %s", exc)
    return fallback
