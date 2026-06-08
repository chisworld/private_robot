"""简单生活上下文：星期、时段、天气。"""

from __future__ import annotations

import logging
from datetime import datetime

from pnn.pet.presence.config import load_presence_config

logger = logging.getLogger(__name__)

_WEEKDAY_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

_PERIOD_RULES: list[tuple[tuple[int, int], str]] = [
    ((0, 5), "深夜"),
    ((5, 8), "清晨"),
    ((8, 11), "上午"),
    ((11, 13), "中午"),
    ((13, 17), "下午"),
    ((17, 19), "傍晚"),
    ((19, 23), "晚上"),
    ((23, 24), "深夜"),
]

def _time_period(hour: int) -> str:
    for (lo, hi), label in _PERIOD_RULES:
        if lo <= hour < hi:
            return label
    return "白天"


def fetch_weather_line(
    *,
    city: str = "",
    enabled: bool = True,
    force_refresh: bool = False,
) -> str:
    from pnn.core.msn_weather import fetch_msn_weather_line

    return fetch_msn_weather_line(city=city, enabled=enabled, force_refresh=force_refresh)


def build_life_context_block(
    now: datetime | None = None,
    *,
    include_weather: bool | None = None,
    weather_city: str | None = None,
) -> str:
    ts = now or datetime.now()
    weekday = _WEEKDAY_ZH[ts.weekday()]
    period = _time_period(ts.hour)
    parts = [f"当前本地：{ts:%Y-%m-%d %H:%M}，{weekday}，{period}。"]
    if ts.weekday() >= 5:
        parts.append("今天是周末。")

    cfg = load_presence_config()
    if include_weather is None:
        include_weather = cfg.presence_weather_enabled
    city = weather_city if weather_city is not None else (cfg.presence_weather_city or "")

    if include_weather:
        weather = fetch_weather_line(city=city, enabled=True)
        if weather:
            parts.append(f"天气参考：{weather}。")

    if cfg.holiday_greeting_enabled:
        from pnn.pet.presence.holidays import holiday_label

        label = holiday_label(ts, user_birthday=cfg.user_birthday)
        if label:
            parts.append(f"今日特殊：{label}。")

    return " ".join(parts)
