"""本机时钟：供 LLM 提示与用户消息注入；时间问句由程序直接作答。"""

from __future__ import annotations

import re
from datetime import datetime

# 询问「现在几点」类短句（不含 [clock] 前缀）
_TIME_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"几点|几点钟|几點|多少点", re.IGNORECASE),
    re.compile(r"(?:现在|当前|此刻).{0,8}(?:几点|时间|几时)", re.IGNORECASE),
    re.compile(r"(?:什么|啥)时间", re.IGNORECASE),
    re.compile(r"何時|今何時|何時ですか|今の時間", re.IGNORECASE),
    re.compile(r"what\s+time\s+is\s+it", re.IGNORECASE),
)


def local_now() -> datetime:
    return datetime.now().astimezone()


def format_clock_system_prompt() -> str:
    """每条对话的系统说明（与下方 [clock] 行一致）。"""
    now = local_now()
    spoken = format_spoken_time(now, lang="zh")
    weekdays = "一二三四五六日"
    wd = weekdays[now.weekday()]
    return (
        f"【程序时钟】本机当前时刻：{now.strftime('%Y年%m月%d日 %H:%M:%S')}（{spoken}），星期{wd}，"
        f"时区 {now.strftime('%z') or '本地'}。"
        "用户消息开头的 [clock] 行由 Python datetime 在请求时生成；"
        "若该行与【程序时钟】不一致，以 [clock] 的 hour/minute 为准。"
        "回答时间相关问题必须与 [clock] 的 hour、minute 完全一致，禁止编造。"
    )


def format_clock_user_prefix() -> str:
    """附在每条用户消息前的机器可读时间行。"""
    now = local_now()
    spoken_zh = format_spoken_time(now, lang="zh")
    spoken_ja = format_spoken_time(now, lang="ja")
    weekdays = "一二三四五六日"
    wd = weekdays[now.weekday()]
    return (
        f"[clock] iso={now.isoformat(timespec='seconds')}; "
        f"local={now.strftime('%Y-%m-%d %H:%M:%S')}; "
        f"weekday=星期{wd}; hour={now.hour}; minute={now.minute}; "
        f"spoken_zh={spoken_zh}; spoken_ja={spoken_ja}"
    )


def prefix_user_message(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return body
    return f"{format_clock_user_prefix()}\n\n{body}"


def format_spoken_time(now: datetime | None = None, *, lang: str = "zh") -> str:
    """口语化时刻（24 小时制，与系统时钟一致）。"""
    dt = now or local_now()
    h, m = dt.hour, dt.minute
    code = (lang or "zh").strip().lower()
    if code in ("ja", "jp"):
        return f"{h}時{m:02d}分"
    if h < 6:
        period = "凌晨"
    elif h < 12:
        period = "上午"
    elif h < 18:
        period = "下午"
    else:
        period = "晚上"
    return f"{period}{h}点{m:02d}分"


def user_asks_current_time(text: str) -> bool:
    """是否为询问当前时刻的短消息（走程序直答，不交给模型猜时间）。"""
    body = (text or "").strip()
    if not body:
        return False
    # 去掉可能已有的 [clock] 行
    body = re.sub(r"^\[clock\][^\n]*\n+", "", body, flags=re.IGNORECASE).strip()
    if len(body) > 120:
        return False
    return any(p.search(body) for p in _TIME_QUERY_PATTERNS)


def build_time_query_reply(
    *,
    char_id: str | None = None,
    lang: str | None = None,
) -> str:
    """由 datetime 生成角色口吻回复（桌宠可带【表情:…】）。"""
    from pnn.characters.reply_lang import active_reply_language, normalize_reply_language

    now = local_now()
    h, m = now.hour, now.minute
    code = normalize_reply_language(lang or active_reply_language())
    cid = (char_id or "").strip()
    try:
        from pnn.llm.config_store import load_llm_config

        if not cid:
            cid = (load_llm_config().active_character or "").strip()
    except Exception:
        pass

    if cid == "里想奈" and code == "ja":
        tail = (
            "もう遅いから、そろそろ休んだ方がいいんじゃない？"
            if h >= 22 or h < 5
            else "お昼寝はちゃんと取った？"
            if 11 <= h < 14
            else ""
        )
        return (
            f"【表情:微笑】ふふ、お兄ちゃんまで時間を聞いてくるの？"
            f"今は{h}時{m:02d}分だよ。"
            f"{tail}"
        ).strip()

    spoken = format_spoken_time(now, lang=code)
    if code == "ja":
        return f"【表情:微笑】今は{spoken}だよ。"
    return f"【表情:微笑】现在是{spoken}哦。"
