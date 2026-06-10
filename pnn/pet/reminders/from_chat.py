"""从对话文本解析未来约定并写入 reminders.json（用户/角色/记忆共用一套规则）。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta

from pnn.pet.reminders.manager import get_reminder_manager
from pnn.pet.reminders.models import Reminder, ReminderStatus

from pnn.pet.reminders.lexicon import (
    ACTIVITY_VERB,
    APPOINTMENT_INTENT,
    COOPERATIVE_PLAN,
    DEFAULT_SOON_MINUTES,
    FUTURE_DAY_REF,
    NEXT_WEEK,
    PERIOD_DEFS,
    RECURRING_REF,
    REMIND_INTENT,
    REL_DAYS,
    REL_HOUR_ZH,
    REL_QUARTER,
    REL_SECONDS,
    REL_WEEKS,
    SCHEDULE_HINT,
    SOON_RELATIVE,
    TITLE_SHORTCUTS,
    WEEK_REF,
)

logger = logging.getLogger(__name__)

_REMIND_INTENT = REMIND_INTENT
_APPOINTMENT_INTENT = APPOINTMENT_INTENT
_SCHEDULE_HINT = SCHEDULE_HINT
_COOPERATIVE_PLAN = COOPERATIVE_PLAN
_ACTIVITY_VERB = ACTIVITY_VERB
_WEEKEND = WEEK_REF
_WEEKDAY = re.compile(r"周([一二三四五六日天])|星期([一二三四五六日天])")
_RECURRING = RECURRING_REF
_SOON_RELATIVE = SOON_RELATIVE
_PAST_ONLY = re.compile(r"昨天|前天|上次|已经|忘了|忘记|没叫|放鸽子|错过了")
_FUTURE_DAY = re.compile(
    r"明天|后天|大后天|明早|明晚|翌日|明儿|明儿个"
)
_TONIGHT = re.compile(r"今晚|今天晚上|今夜|晚间")
_TODAY = re.compile(r"今天|今日|今儿|今儿个")

_TIME_COLON = re.compile(r"(\d{1,2})[：:](\d{2})")
_TIME_ZH = re.compile(r"(\d{1,2})点(\d{1,2})分?")
_TIME_HALF_NUM = re.compile(r"(\d{1,2})点半")
_TIME_ZH_HALF = re.compile(r"([零一二三四五六七八九十两]+)点半")
_TIME_NUM_HOUR = re.compile(r"(\d{1,2})点(?:钟)?(?:整)?")
_TIME_ZH_HOUR = re.compile(r"([零一二三四五六七八九十两]+)点(?:钟)?(?:整)?")
_REL_MINUTES = re.compile(r"(\d+|[零一二三四五六七八九十两]+)\s*分钟(?:之)?后")
_REL_HOURS = re.compile(r"(\d+|[零一二三四五六七八九十两]+)\s*小时(?:之)?后")
_REL_HALF_HOUR = re.compile(r"半(?:个)?小时(?:之)?后|半个钟头(?:之)?后")
_TIME_QUARTER_PAST = re.compile(
    r"(\d{1,2}|[零一二三四五六七八九十两]+)点(?:过|差)?(\d{1,2})分"
)
_TIME_AMPM = re.compile(
    r"(\d{1,2})\s*(?:[：:](\d{2}))?\s*(am|pm|AM|PM|a\.m\.|p\.m\.)"
)
_TIME_DATE_MD = re.compile(
    r"(?:(\d{1,2})月(\d{1,2})[日号]|(\d{1,2})[/-](\d{1,2}))"
)
_TIME_BEFORE_MIN = re.compile(
    r"差(\d{1,2})分(\d{1,2}|[零一二三四五六七八九十两]+)点"
)
_ZH_DIGIT = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

# (pattern, hour, minute, 时段名) — 先匹配更具体的
_PERIOD_SLOTS: tuple[tuple[re.Pattern[str], int, int, str], ...] = tuple(
    (re.compile(pat), h, mi, label) for pat, h, mi, label in PERIOD_DEFS
)

_TITLE_AFTER = re.compile(
    r"提醒(?:我|一下)?(?:该|去|要)?(.+?)(?:了|吧|哦|呀|呢|啊)?\s*$"
)
_TITLE_BEFORE = re.compile(
    r"(?:到|在)?(?:时间|点)?[：:]?\s*(.+?)(?:的?时候)?提醒"
)
_TITLE_CALL = re.compile(r"叫我(?:去|要)?(.+?)(?:了|吧|哦|呀|呢|啊)?\s*$")
_TITLE_REMIND_DO = re.compile(
    r"提醒(?:我|一下)?打(.+?)(?:活动|游戏)?(?:了|吧|哦|呀|呢|啊)?\s*$"
)
_TITLE_CLOCK_REMIND = re.compile(
    r"(?:\d{1,2}|[零一二三四五六七八九十两]+)点(?:钟)?(?:整|半)?"
    r"(?:一定)?(?:要|得)?(?:记得)?提醒(?:我|一下)?(?:去|要|打|该)?(.+?)(?:了|吧|啊|呀|呢|哦)?\s*$"
)
_TITLE_DONOT_FORGET = re.compile(
    r"别忘了(?:.*?)(?:提醒(?:我|一下)?|叫我)(?:去|要|打)?(.+?)(?:了|吧|啊|呀|呢|哦)?\s*$"
)
_TITLE_TOGETHER = re.compile(
    r"一起(?:吃|用|去|洗|睡|玩|看|打|做|练|逛)?([^，。！!？?\s]{1,14})(?:了|吧|哦|吗|呀|呢|啊)?"
)
_TITLE_WE_PLAN = re.compile(
    r"我们(?:一起)?(.+?)(?:吧|好吗|行不行|可以吗|哦|呀|呢|啊)?\s*$"
)
_TITLE_AT_TIME = re.compile(
    r"(?:到|在)?(?:时间|点)?[：:]?\s*(.+?)(?:的?时候|之前|之后)?(?:一起|我们|吧)"
)

_AUTO_TITLE_MAX_LEN = 32
_BAD_TITLE_RE = re.compile(
    r"……|\.{3}|ふん|要是明天|我可就|终于知道|赖床|敲门|不过哥哥"
)
_SLOT_MERGE_SECONDS = 90 * 60
_VAGUE_TITLES = frozenset(
    {
        "吃饭",
        "早饭",
        "早餐",
        "午饭",
        "午餐",
        "晚饭",
        "晚餐",
        "早上",
        "上午",
        "下午",
        "傍晚",
        "晚上",
        "中午",
        "一起晚上",
        "约定事项",
        "夜宵",
        "宵夜",
    }
)
_TITLE_PLAY = re.compile(
    r"玩([^，。！!？?\s]{1,14}?)(?:了|吧|哦|吗|呀|呢|啊)?"
)
_TITLE_EAT_OUT = re.compile(
    r"(?:去|来|吃|喝)(?:点|个|碗)?(.+?)(?:吧|哦|吗|呀|呢|啊)?\s*$"
)
_TITLE_GO_DO = re.compile(
    r"(?:去|来|要|得)(.+?)(?:了|吧|哦|吗|呀|呢|啊)?\s*$"
)
_TITLE_BEFORE_CLOCK = re.compile(
    r"(.+?)(?:的)?(?:时候|时间|点)?[，,]?\s*(?:\d|[零一二三四五六七八九十两])"
)


def _has_cooperative_plan(text: str) -> bool:
    return bool(_COOPERATIVE_PLAN.search(text))


def _has_activity_verb(text: str) -> bool:
    return bool(_ACTIVITY_VERB.search(text))


def _has_remind_intent(text: str) -> bool:
    return bool(_REMIND_INTENT.search(text))


def _has_appointment_intent(text: str) -> bool:
    return bool(_APPOINTMENT_INTENT.search(text))


def _is_past_only_narrative(text: str) -> bool:
    """「昨天说好…」等回顾过去，不算未来日程。"""
    body = (text or "").strip()
    if not body:
        return True
    if re.search(r"别忘了|别忘记", body):
        return False
    if _FUTURE_DAY.search(body) or _TONIGHT.search(body):
        return False
    return bool(_PAST_ONLY.search(body))


def _zh_hour_to_int(token: str) -> int | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        h = int(raw)
        return h if 0 <= h <= 23 else None
    if raw == "十":
        return 10
    if raw.startswith("十") and len(raw) == 2:
        tail = _ZH_DIGIT.get(raw[1])
        return 10 + tail if tail is not None else None
    if raw.endswith("十") and len(raw) == 2:
        head = _ZH_DIGIT.get(raw[0])
        return head * 10 if head is not None else None
    if "十" in raw:
        parts = raw.split("十", 1)
        head = _ZH_DIGIT.get(parts[0], 0) if parts[0] else 1
        tail = _ZH_DIGIT.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        h = head * 10 + tail
        return h if 0 <= h <= 23 else None
    if raw in _ZH_DIGIT:
        h = _ZH_DIGIT[raw]
        return h if 0 <= h <= 23 else None
    return None


def _parse_clock(text: str) -> tuple[int, int] | None:
    body = (text or "").strip()
    if not body:
        return None
    m = _TIME_COLON.search(body)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    m = _TIME_HALF_NUM.search(body)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h, 30
    m = _TIME_ZH_HALF.search(body)
    if m:
        h = _zh_hour_to_int(m.group(1))
        if h is not None:
            return h, 30
    m = _TIME_ZH.search(body)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    m = _TIME_ZH_HOUR.search(body)
    if m:
        h = _zh_hour_to_int(m.group(1))
        if h is not None:
            return h, 0
    m = _TIME_NUM_HOUR.search(body)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h, 0
    m = _TIME_QUARTER_PAST.search(body)
    if m:
        h = _parse_int_token(m.group(1))
        mi = int(m.group(2) or 0)
        if h is not None and 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    m = _TIME_BEFORE_MIN.search(body)
    if m:
        mi_early = int(m.group(1))
        h = _parse_int_token(m.group(2))
        if h is not None and 0 <= h <= 23 and 0 <= mi_early <= 59:
            total = h * 60 - mi_early
            if total < 0:
                total += 24 * 60
            hh, mm = divmod(total, 60)
            return hh % 24, mm
    m = _TIME_AMPM.search(body)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        mer = (m.group(3) or "").lower()
        if mer.startswith("p") and 1 <= h <= 12:
            h = h + 12 if h < 12 else h
        elif mer.startswith("a") and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    return None


def _parse_int_token(token: str) -> int | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    return _zh_hour_to_int(raw)


def _parse_relative_offset(text: str) -> timedelta | None:
    body = (text or "").strip()
    if not body:
        return None
    m = _REL_MINUTES.search(body)
    if m:
        n = _parse_int_token(m.group(1))
        if n is not None and 0 < n <= 24 * 60:
            return timedelta(minutes=n)
    if REL_QUARTER.search(body):
        return timedelta(minutes=15)
    m = _REL_HOURS.search(body)
    if m:
        n = _parse_int_token(m.group(1))
        if n is not None and 0 < n <= 48:
            return timedelta(hours=n)
    if REL_HOUR_ZH.search(body):
        if "半" in body:
            return timedelta(minutes=90)
        return timedelta(hours=1)
    if _REL_HALF_HOUR.search(body):
        return timedelta(minutes=30)
    m = REL_DAYS.search(body)
    if m:
        n = _parse_int_token(m.group(1))
        if n is not None and 0 < n <= 30:
            return timedelta(days=n)
    m = REL_WEEKS.search(body)
    if m:
        n = _parse_int_token(m.group(1)) if m.lastindex and m.group(1) else 1
        if n is None and "两" in body:
            n = 2
        if n is not None and 0 < n <= 8:
            return timedelta(weeks=n)
        if "两周" in body or "二周" in body:
            return timedelta(weeks=2)
        return timedelta(weeks=1)
    m = REL_SECONDS.search(body)
    if m:
        n = int(m.group(1))
        if 0 < n <= 3600:
            return timedelta(seconds=n)
    if _SOON_RELATIVE.search(body) and (
        _has_activity_verb(body)
        or _has_remind_intent(body)
        or _has_cooperative_plan(body)
    ):
        return timedelta(minutes=DEFAULT_SOON_MINUTES)
    return None


def _has_schedule_intent(
    text: str,
    *,
    has_future: bool,
    has_clock: bool = False,
    has_relative: bool = False,
) -> bool:
    body = (text or "").strip()
    if _has_remind_intent(body):
        return True
    if _SCHEDULE_HINT.search(body):
        return True
    if has_relative and (
        _has_remind_intent(body)
        or _has_activity_verb(body)
        or _has_cooperative_plan(body)
    ):
        return True
    if has_clock and (
        _has_activity_verb(body)
        or _has_cooperative_plan(body)
        or _has_appointment_intent(body)
    ):
        return True
    if _has_appointment_intent(body) and has_future:
        return True
    if has_future and _has_activity_verb(body):
        return True
    if _has_cooperative_plan(body) and _has_activity_verb(body):
        return True
    return False


def _has_future_reference(text: str) -> bool:
    body = (text or "").strip()
    if _FUTURE_DAY.search(body) or _TONIGHT.search(body) or _TODAY.search(body):
        return True
    if FUTURE_DAY_REF.search(body) or _WEEKEND.search(body) or _WEEKDAY.search(body):
        return True
    if NEXT_WEEK.search(body):
        return True
    if _RECURRING.search(body):
        return True
    return False


def _weekday_target(text: str) -> int | None:
    """返回 0=周一 … 6=周日；未命中则 None。"""
    m = _WEEKDAY.search(text or "")
    if not m:
        return None
    token = (m.group(1) or m.group(2) or "").strip()
    mapping = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    return mapping.get(token)


def _weekend_date(now: datetime) -> datetime.date:
    wd = now.weekday()
    if wd == 5:
        return now.date()
    if wd == 6:
        return now.date()
    days = (5 - wd) % 7
    if days == 0:
        days = 7
    return (now + timedelta(days=days)).date()


def _day_offset(text: str) -> int:
    if "大后天" in text:
        return 3
    if "后天" in text:
        return 2
    if _FUTURE_DAY.search(text):
        return 1
    return 0


def _resolve_weekday_date(text: str, now: datetime) -> datetime.date | None:
    if NEXT_WEEK.search(text or ""):
        target = _weekday_target(text)
        base = now.date() + timedelta(days=7)
        if target is not None:
            days = (target - base.weekday()) % 7
            return base + timedelta(days=days)
        return base + timedelta(days=(7 - now.weekday()) % 7 or 7)
    if _WEEKEND.search(text or ""):
        base = _weekend_date(now)
        if "下周末" in text:
            return base + timedelta(days=7)
        return base
    target = _weekday_target(text)
    if target is None:
        return None
    days = (target - now.weekday()) % 7
    if days == 0 and not _TODAY.search(text or ""):
        days = 7
    return (now + timedelta(days=days)).date()


def _match_period_slot(text: str) -> tuple[int, int, str] | None:
    body = (text or "").strip()
    for pat, h, mi, label in _PERIOD_SLOTS:
        if pat.search(body):
            return h, mi, label
    return None


def _apply_day_period(text: str, h: int, mi: int) -> tuple[int, int]:
    """「下午三点」→ 15:00 等。"""
    body = text or ""
    if re.search(r"下午|午后|傍晚", body) and 1 <= h <= 11:
        return h + 12, mi
    if re.search(r"晚上|夜里|夜间|今晚|今夜", body) and 1 <= h <= 11:
        return h + 12, mi
    if re.search(r"凌晨", body) and h == 12:
        return 0, mi
    return h, mi


def _adjust_ambiguous_hour(
    h: int,
    mi: int,
    now: datetime,
    text: str = "",
) -> tuple[int, int]:
    if h > 12 or now.hour < 12:
        return h, mi
    body = text or ""
    if any(k in body for k in ("早上", "凌晨", "上午", "早晨", "明早", "早饭", "早餐")):
        return h, mi
    evening = h + 12
    if evening > 23:
        return h, mi
    today = now.date()
    raw_start = datetime.combine(today, time(h, mi))
    if raw_start <= now:
        raw_start += timedelta(days=1)
    eve_start = datetime.combine(today, time(evening, mi))
    if eve_start <= now:
        eve_start += timedelta(days=1)
    if (eve_start - now).total_seconds() < (raw_start - now).total_seconds():
        return evening, mi
    return h, mi


def is_valid_auto_title(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) > _AUTO_TITLE_MAX_LEN:
        return False
    if _BAD_TITLE_RE.search(t):
        return False
    if re.search(r"[\u3040-\u30ff\u31f0-\u31ff]", t):
        return False
    if "……" in t or "..." in t:
        return False
    return True


def _is_vague_title(title: str) -> bool:
    t = (title or "").strip()
    if not t or t in _VAGUE_TITLES:
        return True
    if t.startswith("一起吃") and len(t) <= 6:
        return True
    if t.startswith("一起") and len(t) <= 6:
        return True
    if re.fullmatch(r"吃(早上|上午|下午|晚上|中午|午饭|晚饭|早餐|晚餐)", t):
        return True
    return False


def _same_appointment_topic(
    old_title: str,
    new_title: str,
    *,
    raw_hint: str = "",
) -> bool:
    """润色前后标题不同，但同一事项（如都含「黄焖鸡米饭」）。"""
    a = (old_title or "").strip()
    b = (new_title or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    raw = (raw_hint or "").strip()
    if raw and len(raw) >= 2:
        if a == raw or b == raw:
            return True
        if raw in a and raw in b:
            return True
    return False


def _title_quality(title: str) -> int:
    if not is_valid_auto_title(title):
        return -100
    if title == "起床":
        return 100
    if _is_vague_title(title):
        return 30
    return 60 + min(20, len(title))


def _is_bad_title_fragment(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return True
    if re.fullmatch(r"[\d\s：:.,，点分秒amAMpmPM]+", t):
        return True
    if t in _VAGUE_TITLES:
        return True
    if re.fullmatch(r"(今天|明天|后天|大后天|今晚|明早|明晚|上午|下午|晚上|中午|后天下午|后天早上).*", t):
        return True
    return False


def _extract_title(text: str, period_label: str = "") -> str:
    body = (text or "").strip()
    for key, short in TITLE_SHORTCUTS:
        if key in body:
            return short[:_AUTO_TITLE_MAX_LEN]
    if re.search(r"(?:am|pm)\s*$", body, re.I) and re.search(r"叫我|喊我", body):
        return "起床"
    if re.search(r"叫我\s*$|喊我\s*$", body):
        return "起床"
    if re.search(r"叫他起床|叫我起床|叫醒|喊我起床|叫我起来", body):
        return "起床"
    if re.search(r"睡觉|睡吧|入睡|就寝|熄灯|入眠", body):
        if re.search(r"我们|一起|咱俩", body):
            return "一起睡觉"
        return "睡觉"
    if re.search(r"洗澡|泡澡|沐浴|搓背|淋浴", body):
        if re.search(r"我们|一起|咱俩", body):
            return "一起洗澡"
        return "洗澡"
    if re.search(r"吃药|取药|敷药", body):
        m = re.search(r"吃(.{1,8}?)(?:了|吧|哦|呀|呢|啊)?", body)
        if m and m.group(1).strip():
            return f"吃{m.group(1).strip()}"[:_AUTO_TITLE_MAX_LEN]
        return "吃药"
    if re.search(r"开会|会议", body):
        return "开会"
    if re.search(r"打电话|视频|语音", body):
        return "联系"
    play = _TITLE_PLAY.search(body)
    if play:
        game = (play.group(1) or "").strip()
        game = re.sub(r"[吧哦吗呀呢啊]+$", "", game).strip()
        if game:
            return f"玩{game}"[:_AUTO_TITLE_MAX_LEN]
    eat_out = _TITLE_EAT_OUT.search(body)
    if eat_out:
        food = (eat_out.group(1) or "").strip()
        food = re.sub(r"[吧哦吗呀呢啊]+$", "", food).strip()
        if food and len(food) >= 2 and not re.fullmatch(r"[点分秒]", food):
            if food.startswith("饭") and len(food) <= 3:
                pass
            else:
                return food[:_AUTO_TITLE_MAX_LEN]
    go_do = _TITLE_GO_DO.search(body)
    if go_do and _has_remind_intent(body):
        frag = (go_do.group(1) or "").strip()
        frag = re.sub(r"[吧哦吗呀呢啊]+$", "", frag).strip()
        if frag and 2 <= len(frag) <= _AUTO_TITLE_MAX_LEN:
            return frag
    m_before = _TITLE_BEFORE_CLOCK.search(body)
    if m_before:
        frag = (m_before.group(1) or "").strip()
        if frag and not _is_bad_title_fragment(frag) and len(frag) <= _AUTO_TITLE_MAX_LEN:
            return frag
    meal = re.search(
        r"一起吃(早饭|早餐|午饭|午餐|晚饭|晚餐|夜宵|宵夜|粽子|饭)",
        body,
    )
    if meal:
        return f"一起吃{meal.group(1)}"[:40]
    m = _TITLE_TOGETHER.search(body)
    if m:
        frag = (m.group(1) or "").strip()
        frag = re.sub(r"^(吃|用|去|洗|睡|玩|看|打|做|练|逛)", "", frag).strip()
        frag = re.sub(r"[吧哦吗呀呢啊]+$", "", frag).strip()
        if frag:
            return f"一起{frag}"[:40]
    m = _TITLE_WE_PLAN.search(body)
    if m:
        frag = (m.group(1) or "").strip()
        frag = re.sub(r"^[，,。\s]+", "", frag)
        frag = re.sub(r"[吧哦吗呀呢啊]+$", "", frag).strip()
        frag = _TIME_COLON.sub("", frag)
        frag = _TIME_HALF_NUM.sub("", frag)
        frag = _TIME_ZH_HALF.sub("", frag)
        frag = _TIME_ZH.sub("", frag)
        frag = _TIME_ZH_HOUR.sub("", frag)
        frag = _TIME_NUM_HOUR.sub("", frag)
        frag = re.sub(r"^[点：:\s]+", "", frag).strip()
        if frag and len(frag) <= _AUTO_TITLE_MAX_LEN:
            if re.search(r"睡", frag):
                return "一起睡觉" if re.search(r"一起|我们", body) else "睡觉"
            return frag[:40]
    m = _TITLE_AT_TIME.search(body)
    if m:
        frag = (m.group(1) or "").strip()
        if frag and len(frag) <= _AUTO_TITLE_MAX_LEN:
            return frag
    if re.search(r"追(?:剧|番|更)", body):
        return "追剧"
    if re.search(r"跑步|慢跑", body):
        return "跑步"
    act = _ACTIVITY_VERB.search(body)
    if act:
        word = act.group(0)
        if len(word) >= 2 and word not in ("一起", "我们", "明天", "今天"):
            return word[:_AUTO_TITLE_MAX_LEN]
    if period_label and re.search(r"一起|约|去吃", body):
        return f"一起{period_label}"[:40]
    if period_label and re.search(r"吃|用餐|饭", body):
        return f"吃{period_label}"[:40]
    m = _TITLE_REMIND_DO.search(body)
    if m:
        title = (m.group(1) or "").strip()
        title = re.sub(r"[吧哦吗呀呢啊]+$", "", title).strip()
        if title:
            return title[:_AUTO_TITLE_MAX_LEN]
    m = _TITLE_CLOCK_REMIND.search(body)
    if m:
        title = (m.group(1) or "").strip()
        title = re.sub(r"[吧哦吗呀呢啊]+$", "", title).strip()
        if title:
            return title[:_AUTO_TITLE_MAX_LEN]
    m = _TITLE_DONOT_FORGET.search(body)
    if m:
        title = (m.group(1) or "").strip()
        title = re.sub(r"[吧哦吗呀呢啊]+$", "", title).strip()
        if title:
            return title[:_AUTO_TITLE_MAX_LEN]
    for pat in (_TITLE_AFTER, _TITLE_BEFORE, _TITLE_CALL):
        m = pat.search(body)
        if m:
            title = (m.group(1) or "").strip()
            title = re.sub(r"^[：:，,\s]+", "", title)
            title = re.sub(r"^我", "", title).strip()
            if title and len(title) <= 40:
                return title
    if re.search(r"起床|起来|叫醒", body):
        return "起床"
    if period_label:
        return period_label
    scrub = _TIME_COLON.sub("", body)
    scrub = _TIME_HALF_NUM.sub("", scrub)
    scrub = _TIME_ZH_HALF.sub("", scrub)
    scrub = _TIME_ZH.sub("", scrub)
    scrub = _TIME_ZH_HOUR.sub("", scrub)
    scrub = _TIME_NUM_HOUR.sub("", scrub)
    scrub = _TIME_AMPM.sub("", scrub)
    scrub = _REL_MINUTES.sub("", scrub)
    scrub = _REL_HOURS.sub("", scrub)
    scrub = re.sub(r"半(?:个)?小时(?:之)?后", "", scrub)
    scrub = re.sub(r"提醒(?:我|一下)?(?:该|去|要)?", "", scrub)
    scrub = re.sub(r"[了吧哦呀呢啊\s]+", "", scrub).strip()
    if scrub and len(scrub) <= _AUTO_TITLE_MAX_LEN and not _is_bad_title_fragment(scrub):
        return scrub
    act = _ACTIVITY_VERB.search(body)
    if act:
        word = act.group(0)
        if len(word) >= 2:
            return word[:_AUTO_TITLE_MAX_LEN]
    return period_label or "约定事项"


def _resolve_calendar_date(text: str, now: datetime) -> datetime.date | None:
    body = text or ""
    m = _TIME_DATE_MD.search(body)
    if not m:
        return None
    if m.group(1) and m.group(2):
        month, day = int(m.group(1)), int(m.group(2))
    else:
        month, day = int(m.group(3)), int(m.group(4))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = now.year
    try:
        candidate = datetime(year, month, day).date()
    except ValueError:
        return None
    if candidate < now.date() and not _TODAY.search(body):
        try:
            candidate = datetime(year + 1, month, day).date()
        except ValueError:
            return None
    return candidate


def _resolve_start_datetime(
    text: str,
    *,
    hour: int,
    minute: int,
    now: datetime,
) -> datetime:
    weekday_date = _resolve_weekday_date(text, now)
    calendar_date = _resolve_calendar_date(text, now)
    offset = _day_offset(text)
    if _TONIGHT.search(text):
        start = datetime.combine(now.date(), time(hour, minute))
        if start <= now:
            start += timedelta(days=1)
        return start
    if calendar_date is not None:
        start = datetime.combine(calendar_date, time(hour, minute))
        if start <= now and not _TODAY.search(text):
            return start + timedelta(days=365) if calendar_date.year == now.year else start
        if start <= now:
            start += timedelta(days=1)
        return start
    if weekday_date is not None:
        start = datetime.combine(weekday_date, time(hour, minute))
        if start <= now:
            start += timedelta(days=7)
        return start
    if _TODAY.search(text) and offset == 0:
        start = datetime.combine(now.date(), time(hour, minute))
        if start <= now:
            start += timedelta(days=1)
        return start
    if offset == 0:
        # 没有明确说"今天/明天/后天"时，根据具体时间判断：
        # 若该时间在今天尚未过去，就是今天；否则推到明天
        start = datetime.combine(now.date(), time(hour, minute))
        if start <= now:
            start += timedelta(days=1)
        return start
    start = datetime.combine((now + timedelta(days=offset)).date(), time(hour, minute))
    if start <= now:
        start += timedelta(days=1)
    return start


def parse_reminder_request(
    text: str,
    *,
    now: datetime | None = None,
    require_intent: bool = True,
) -> tuple[str, datetime, datetime] | None:
    """解析未来约定。用户/角色回复/记忆 event 共用。"""
    body = (text or "").strip()
    if not body or _is_past_only_narrative(body):
        return None

    ts = now or datetime.now()
    clock = _parse_clock(body)
    period = _match_period_slot(body)
    has_future = _has_future_reference(body)
    rel = _parse_relative_offset(body)
    intent_kw = dict(
        has_future=has_future,
        has_clock=clock is not None,
        has_relative=rel is not None,
    )

    if rel is not None:
        if require_intent and not _has_schedule_intent(body, **intent_kw):
            return None
        start = ts + rel
        title = _extract_title(body, period[2] if period else "")
    elif clock is not None:
        if require_intent and not _has_schedule_intent(body, **intent_kw):
            return None
        h, mi = clock[0], clock[1]
        h, mi = _apply_day_period(body, h, mi)
        h, mi = _adjust_ambiguous_hour(h, mi, ts, body)
        start = _resolve_start_datetime(body, hour=h, minute=mi, now=ts)
        title = _extract_title(body, period[2] if period else "")
    elif period is not None and (
        has_future
        or _has_remind_intent(body)
        or _has_cooperative_plan(body)
        or (_SCHEDULE_HINT.search(body) and _has_activity_verb(body))
    ):
        if require_intent and not _has_schedule_intent(body, **intent_kw):
            return None
        h, mi, label = period
        start = _resolve_start_datetime(body, hour=h, minute=mi, now=ts)
        title = _extract_title(body, label)
    elif has_future and (_has_appointment_intent(body) or _has_activity_verb(body)):
        if require_intent and not _has_schedule_intent(body, **intent_kw):
            return None
        # 「明天一起吃饭」「周末去爬山」等：按时段或默认中午
        if period is not None:
            h, mi, label = period
        else:
            h, mi, label = 12, 0, "约定"
        start = _resolve_start_datetime(body, hour=h, minute=mi, now=ts)
        title = _extract_title(body, label)
    else:
        return None

    end = start + timedelta(minutes=30)
    return title, start, end


def parse_user_reminder_request(
    text: str,
    *,
    now: datetime | None = None,
    require_intent: bool = True,
) -> tuple[str, datetime, datetime] | None:
    return parse_reminder_request(text, now=now, require_intent=require_intent)


def _slot_conflict_blocks_create(
    session_key: str,
    title: str,
    start: datetime,
    *,
    raw_title: str = "",
) -> bool:
    """同天同时段已有待办：模糊项让位给更具体约定；完全相同则跳过。"""
    mgr = get_reminder_manager()
    new_title = (title or "").strip()
    topic = (raw_title or "").strip() or new_title
    for r in list(mgr.list_for_session(session_key, status=ReminderStatus.pending)):
        if r.scheduled_start.date() != start.date():
            continue
        if abs((r.scheduled_start - start).total_seconds()) >= _SLOT_MERGE_SECONDS:
            continue
        old_title = r.title.strip()
        if _same_appointment_topic(old_title, new_title, raw_hint=topic):
            mgr.delete(r.id)
            logger.info(
                "待办已改期: %s @ %s → %s @ %s",
                old_title,
                r.scheduled_start.strftime("%m-%d %H:%M"),
                new_title,
                start.strftime("%m-%d %H:%M"),
            )
            continue
        if _is_vague_title(old_title) or _title_quality(new_title) > _title_quality(
            old_title
        ):
            mgr.delete(r.id)
            logger.info(
                "待办已更新: %s → %s @ %s",
                old_title,
                new_title,
                start.strftime("%m-%d %H:%M"),
            )
            continue
        return True
    return False


def cleanup_session_reminders(session_key: str) -> int:
    """清理垃圾/重复待办：保留同时间段质量最高的一条。"""
    sk = (session_key or "").strip() or "__default__"
    mgr = get_reminder_manager()
    mgr.reload()
    pending = [
        r
        for r in mgr.list_for_session(sk, status=ReminderStatus.pending)
        if r.source != "manual"
    ]
    if not pending:
        return 0

    clusters: list[list[Reminder]] = []
    for r in sorted(pending, key=lambda x: x.scheduled_start):
        placed = False
        for cluster in clusters:
            anchor = cluster[0]
            if anchor.scheduled_start.date() != r.scheduled_start.date():
                continue
            if (
                abs((anchor.scheduled_start - r.scheduled_start).total_seconds())
                < _SLOT_MERGE_SECONDS
            ):
                cluster.append(r)
                placed = True
                break
        if not placed:
            clusters.append([r])

    removed = 0
    for cluster in clusters:
        if len(cluster) == 1:
            only = cluster[0]
            if not is_valid_auto_title(only.title):
                if mgr.delete(only.id):
                    removed += 1
            continue
        best = max(
            cluster,
            key=lambda r: (_title_quality(r.title), -len(r.title)),
        )
        for r in cluster:
            if r.id == best.id:
                continue
            if mgr.delete(r.id):
                removed += 1
    if removed:
        logger.info("已清理重复/垃圾待办 %d 条（%s）", removed, sk)
    return removed


def try_create_reminder_from_text(
    session_key: str,
    text: str,
    *,
    character_name: str = "",
    character_id: str = "",
    now: datetime | None = None,
    require_intent: bool = True,
    source: str = "chat",
    polish_title: bool = False,
) -> Reminder | None:
    """用户/角色/记忆统一入口：解析成功则写入 reminders.json。"""
    parsed = parse_reminder_request(
        text,
        now=now,
        require_intent=require_intent,
    )
    if parsed is None:
        return None
    raw_title, start, end = parsed
    display_title = raw_title
    if polish_title and source == "chat":
        from pnn.pet.reminders.title_polish import polish_reminder_title

        display_title = polish_reminder_title(
            text,
            raw_title,
            start,
            character_id=character_id,
            character_name=character_name,
        )
    if not is_valid_auto_title(display_title):
        logger.debug("跳过无效待办标题: %s", display_title[:40])
        return None
    sk = (session_key or "").strip() or "__default__"
    if _slot_conflict_blocks_create(
        sk,
        display_title,
        start,
        raw_title=raw_title,
    ):
        logger.info(
            "跳过重复日程: %s @ %s",
            display_title,
            start.strftime("%H:%M"),
        )
        return None
    launch_app_id = ""
    try:
        from pnn.launch_apps.service import launch_apps_service

        app = launch_apps_service.find_app_in_text(text)
        if app is None:
            app = launch_apps_service.find_app_in_text(display_title)
        if app is not None:
            launch_app_id = app.id
            logger.info("日程绑定快捷启动: %s → %s", display_title, app.label)
    except Exception:
        logger.debug("匹配快捷启动失败", exc_info=True)
    mgr = get_reminder_manager()
    reminder = mgr.create(
        session_key=sk,
        title=display_title,
        scheduled_start=start,
        scheduled_end=end,
        character_name=(character_name or "").strip(),
        source=source,
        launch_app_id=launch_app_id,
    )
    logger.info(
        "已创建日程提醒: %s @ %s（%s）",
        display_title,
        start.strftime("%Y-%m-%d %H:%M"),
        source,
    )
    return reminder


def try_create_reminder_from_user_message(
    session_key: str,
    text: str,
    *,
    character_name: str = "",
    character_id: str = "",
    now: datetime | None = None,
) -> Reminder | None:
    return try_create_reminder_from_text(
        session_key,
        text,
        character_name=character_name,
        character_id=character_id,
        now=now,
        require_intent=True,
        source="chat",
        polish_title=True,
    )


def try_create_reminder_from_memory_event(
    session_key: str,
    content: str,
    *,
    character_name: str = "",
    now: datetime | None = None,
) -> Reminder | None:
    """不再从记忆摘要建待办（易重复、易编造）；仅用户原话创建。"""
    _ = (session_key, content, character_name, now)
    return None


def try_create_reminder_from_assistant_reply(
    session_key: str,
    text: str,
    *,
    character_name: str = "",
    now: datetime | None = None,
) -> Reminder | None:
    """不再从整段角色回复建待办（易把台词当约定）。"""
    _ = (session_key, text, character_name, now)
    return None
