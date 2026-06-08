"""从对话文本解析未来约定并写入 reminders.json（用户/角色/记忆共用一套规则）。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta

from pnn.pet.reminders.manager import get_reminder_manager
from pnn.pet.reminders.models import Reminder, ReminderStatus

logger = logging.getLogger(__name__)

_REMIND_INTENT = re.compile(
    r"提醒|叫我|喊我|记得(?:一定|要|得)?(?:要)?(?:提醒|叫)|"
    r"一定要记得|别忘了|别忘|闹钟|定时|通知我|"
    r"帮我设(?:个|置)?|设置(?:一个)?提醒|到点(?:要|得)?|准时(?:要|得)?(?:叫|提醒)"
)
_APPOINTMENT_INTENT = re.compile(
    r"一起|约|约好|说好|约定|记得|准时|会叫|喊我|叫我|去吃|吃饭|用餐|"
    r"起床|起来|见面|叫醒|别忘了|别忘|午饭|早餐|晚饭|晚餐|午饭"
)
_SCHEDULE_HINT = re.compile(r"提醒|叫我|约定|到点|时候|说好|约好")
_PAST_ONLY = re.compile(r"昨天|前天|上次|已经|忘了|忘记|没叫|放鸽子|错过了")
_FUTURE_DAY = re.compile(r"明天|后天|大后天|明早|明晚|翌日")
_TONIGHT = re.compile(r"今晚|今天晚上|今夜")
_TODAY = re.compile(r"今天|今日")

_TIME_COLON = re.compile(r"(\d{1,2})[：:](\d{2})")
_TIME_ZH = re.compile(r"(\d{1,2})点(\d{1,2})分?")
_TIME_HALF_NUM = re.compile(r"(\d{1,2})点半")
_TIME_ZH_HALF = re.compile(r"([零一二三四五六七八九十两]+)点半")
_TIME_NUM_HOUR = re.compile(r"(\d{1,2})点(?:钟)?(?:整)?")
_TIME_ZH_HOUR = re.compile(r"([零一二三四五六七八九十两]+)点(?:钟)?(?:整)?")
_REL_MINUTES = re.compile(r"(\d+|[零一二三四五六七八九十两]+)\s*分钟(?:之)?后")
_REL_HOURS = re.compile(r"(\d+|[零一二三四五六七八九十两]+)\s*小时(?:之)?后")
_REL_HALF_HOUR = re.compile(r"半(?:个)?小时(?:之)?后")
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
_PERIOD_SLOTS: tuple[tuple[re.Pattern[str], int, int, str], ...] = (
    (re.compile(r"早饭|早餐"), 7, 30, "早餐"),
    (re.compile(r"午饭|午餐"), 12, 0, "午饭"),
    (re.compile(r"晚饭|晚餐"), 18, 30, "晚饭"),
    (re.compile(r"夜宵|宵夜"), 21, 30, "夜宵"),
    (re.compile(r"中午|正午"), 12, 0, "中午"),
    (re.compile(r"上午"), 10, 0, "上午"),
    (re.compile(r"下午"), 15, 0, "下午"),
    (re.compile(r"傍晚"), 18, 0, "傍晚"),
    (re.compile(r"明早|清晨|早起|起床|起来|早上|早晨"), 7, 30, "早上"),
    (re.compile(r"晚上|今晚|夜里|夜间"), 19, 30, "晚上"),
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
    r"一起(?:吃|用|去)?([^，。！!？?\s]{1,14}?)(?:吧|哦|吗|呀|呢|啊)?"
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
    r"(?:去|来)吃(.+?)(?:吧|哦|吗|呀|呢|啊)?\s*$"
)


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
    m = _REL_HOURS.search(body)
    if m:
        n = _parse_int_token(m.group(1))
        if n is not None and 0 < n <= 48:
            return timedelta(hours=n)
    if _REL_HALF_HOUR.search(body):
        return timedelta(minutes=30)
    return None


def _has_schedule_intent(text: str, *, has_future: bool) -> bool:
    body = (text or "").strip()
    return bool(
        _has_remind_intent(body)
        or (_has_appointment_intent(body) and has_future)
        or _SCHEDULE_HINT.search(body)
    )


def _day_offset(text: str) -> int:
    if "大后天" in text:
        return 3
    if "后天" in text:
        return 2
    if _FUTURE_DAY.search(text):
        return 1
    return 0


def _match_period_slot(text: str) -> tuple[int, int, str] | None:
    body = (text or "").strip()
    for pat, h, mi, label in _PERIOD_SLOTS:
        if pat.search(body):
            return h, mi, label
    return None


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


def _extract_title(text: str, period_label: str = "") -> str:
    body = (text or "").strip()
    if re.search(r"叫他起床|叫我起床|叫醒|喊我起床|叫我起来", body):
        return "起床"
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
        if food:
            return food[:_AUTO_TITLE_MAX_LEN]
    meal = re.search(
        r"一起吃(早饭|早餐|午饭|午餐|晚饭|晚餐|夜宵|宵夜|粽子|饭)",
        body,
    )
    if meal:
        return f"一起吃{meal.group(1)}"[:40]
    m = _TITLE_TOGETHER.search(body)
    if m:
        frag = (m.group(1) or "").strip()
        frag = re.sub(r"^(吃|用|去)", "", frag).strip()
        frag = re.sub(r"[吧哦吗呀呢啊]+$", "", frag).strip()
        if frag:
            return f"一起{frag}"[:40]
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
    scrub = _REL_MINUTES.sub("", scrub)
    scrub = _REL_HOURS.sub("", scrub)
    scrub = re.sub(r"半(?:个)?小时(?:之)?后", "", scrub)
    scrub = re.sub(r"提醒(?:我|一下)?(?:该|去|要)?", "", scrub)
    scrub = re.sub(r"[了吧哦呀呢啊\s]+", "", scrub).strip()
    if scrub and len(scrub) <= _AUTO_TITLE_MAX_LEN:
        return scrub
    return period_label or "约定事项"


def _resolve_start_datetime(
    text: str,
    *,
    hour: int,
    minute: int,
    now: datetime,
) -> datetime:
    offset = _day_offset(text)
    if _TONIGHT.search(text):
        start = datetime.combine(now.date(), time(hour, minute))
        if start <= now:
            start += timedelta(days=1)
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
    has_future = bool(_FUTURE_DAY.search(body) or _TONIGHT.search(body) or _TODAY.search(body))
    rel = _parse_relative_offset(body)

    if rel is not None:
        if require_intent and not _has_schedule_intent(body, has_future=has_future):
            return None
        start = ts + rel
        title = _extract_title(body, period[2] if period else "")
    elif clock is not None:
        if require_intent and not _has_schedule_intent(body, has_future=has_future):
            return None
        h, mi = _adjust_ambiguous_hour(clock[0], clock[1], ts, body)
        start = _resolve_start_datetime(body, hour=h, minute=mi, now=ts)
        title = _extract_title(body, period[2] if period else "")
    elif period is not None and (has_future or _has_remind_intent(body)):
        if require_intent and not _has_schedule_intent(body, has_future=has_future):
            return None
        h, mi, label = period
        start = _resolve_start_datetime(body, hour=h, minute=mi, now=ts)
        title = _extract_title(body, label)
    elif has_future and _has_appointment_intent(body):
        # 「明天一起吃饭」等：默认中午
        h, mi, label = 12, 0, "吃饭"
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
