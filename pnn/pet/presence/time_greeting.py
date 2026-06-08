"""时段问候：每日每时段最多一次。"""

from __future__ import annotations

from datetime import datetime

from pnn.pet.presence.life_context import _time_period


def time_greeting_key(now: datetime | None = None) -> str:
    ts = now or datetime.now()
    period = _time_period(ts.hour)
    return f"{ts:%Y-%m-%d}-{period}"


def time_greeting_period_label(now: datetime | None = None) -> str:
    ts = now or datetime.now()
    return _time_period(ts.hour)
