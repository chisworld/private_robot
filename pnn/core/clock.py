"""本机时钟：供 LLM 提示与用户消息注入；时间问句注入事实后由 LLM 按角色设定转述。"""

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
    """内部时钟说明：仅供用户明确问时间时使用，禁止闲聊时主动报时。"""
    now = local_now()
    weekdays = "一二三四五六日"
    wd = weekdays[now.weekday()]
    return (
        f"【程序时钟·内部参考】本机：{now.strftime('%Y-%m-%d %H:%M')} 星期{wd}。"
        "用户未明确询问「几点/现在什么时间」时，回复中禁止主动说出具体时刻"
        "（例如「已经19点」「19時24分」「晚上7点了」等），也不要用报时开场。"
        "用户明确问时间时，须与程序时钟一致，禁止编造。"
        "每条用户消息均附带 [clock] 行（hour、minute、spoken_zh 为本机准确值）。"
        "若仍提到当前时刻或距某约定还剩多久，必须按 [clock] 推算，禁止编造"
        "（例如实际 20:08 不可说成 20:31）。"
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
    """是否为询问当前时刻的短消息（注入 [clock] 与系统上下文，禁止模型猜时间）。"""
    body = (text or "").strip()
    if not body:
        return False
    # 去掉可能已有的 [clock] 行
    body = re.sub(r"^\[clock\][^\n]*\n+", "", body, flags=re.IGNORECASE).strip()
    if len(body) > 120:
        return False
    return any(p.search(body) for p in _TIME_QUERY_PATTERNS)


def _time_reply_rules() -> str:
    return (
        "【程序时钟·回答规则】用户正在询问当前时刻；时刻须与【程序时钟·当前】及"
        "用户消息 [clock] 行的 hour、minute 完全一致，禁止编造。"
        "用【角色设定】口吻自然回答；禁止说「稍等」「我去查」。"
    )


def build_time_query_system_context(user_message: str) -> str | None:
    """时间问句：注入本机时刻，供 LLM 用角色口吻转述（不写死任何角色 ID）。"""
    if not user_asks_current_time(user_message):
        return None
    now = local_now()
    weekdays = "一二三四五六日"
    wd = weekdays[now.weekday()]
    spoken_zh = format_spoken_time(now, lang="zh")
    spoken_ja = format_spoken_time(now, lang="ja")
    return (
        f"【程序时钟·当前】{now.strftime('%Y-%m-%d %H:%M')} 星期{wd}；"
        f"hour={now.hour}; minute={now.minute}；"
        f"spoken_zh={spoken_zh}；spoken_ja={spoken_ja}。"
        f"{_time_reply_rules()}"
    )
