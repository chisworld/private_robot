"""固定公历节日与用户生日检测。"""

from __future__ import annotations

import re
from datetime import datetime

_FIXED: dict[str, str] = {
    "01-01": "元旦",
    "02-14": "情人节",
    "03-08": "妇女节",
    "05-01": "劳动节",
    "05-20": "520",
    "06-01": "儿童节",
    "10-01": "国庆节",
    "12-24": "平安夜",
    "12-25": "圣诞节",
}

_BIRTHDAY_MD_RE = re.compile(r"^(\d{1,2})[-/](\d{1,2})$")


def normalize_birthday_md(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    m = _BIRTHDAY_MD_RE.match(text)
    if not m:
        return ""
    mm = int(m.group(1))
    dd = int(m.group(2))
    if mm < 1 or mm > 12 or dd < 1 or dd > 31:
        return ""
    return f"{mm:02d}-{dd:02d}"


def holiday_label(now: datetime | None = None, *, user_birthday: str = "") -> str | None:
    ts = now or datetime.now()
    md = ts.strftime("%m-%d")
    if md in _FIXED:
        return _FIXED[md]
    bday = normalize_birthday_md(user_birthday)
    if bday and md == bday:
        return "用户生日"
    return None


def holiday_greeting_key(now: datetime, label: str) -> str:
    return f"{now:%Y-%m-%d}-{label}"
