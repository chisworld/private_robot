"""通过 Playwright（Edge）抓取 MSN 天气页面。"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

MSN_WEATHER_BASE = "https://www.msn.cn/zh-cn/weather/forecast/in-"
_CACHE_TTL = 1800.0
_WEEKDAY_ZH = "一二三四五六日"
_weather_cache: tuple[str, float] = ("", 0.0)
_snapshot_cache: tuple[tuple[str, str], MsnWeatherSnapshot | None, float] = (("", ""), None, 0.0)

_CONDITION_WORDS: tuple[str, ...] = (
    "大部多云",
    "局部多云",
    "雷阵雨",
    "阵雨",
    "多云",
    "晴朗",
    "暴雨",
    "小雨",
    "中雨",
    "大雨",
    "暴雪",
    "小雪",
    "中雪",
    "大雪",
    "阴",
    "雾",
    "雪",
    "雨",
    "晴",
)

# 数值越大越优先（同窗口内多命中时取最重天气）
_CONDITION_SEVERITY: dict[str, int] = {
    "暴雨": 100,
    "暴雪": 95,
    "大雨": 90,
    "大雪": 85,
    "中雨": 70,
    "中雪": 68,
    "雷阵雨": 65,
    "阵雨": 62,
    "小雨": 55,
    "小雪": 53,
    "雨": 50,
    "雪": 48,
    "雾": 40,
    "阴": 35,
    "大部多云": 30,
    "局部多云": 28,
    "多云": 25,
    "晴朗": 15,
    "晴": 10,
}

# 常见城市 → MSN 路径「省,市」（未命中时直接用用户填写的城市名）
_CITY_TO_MSN_LOC: dict[str, str] = {
    "温州": "浙江省,温州市",
    "龙港": "浙江省,龙港市",
    "杭州": "浙江省,杭州市",
    "宁波": "浙江省,宁波市",
    "上海": "上海市,上海市",
    "北京": "北京市,北京市",
    "天津": "天津市,天津市",
    "重庆": "重庆市,重庆市",
    "广州": "广东省,广州市",
    "深圳": "广东省,深圳市",
    "成都": "四川省,成都市",
    "武汉": "湖北省,武汉市",
    "西安": "陕西省,西安市",
    "南京": "江苏省,南京市",
    "苏州": "江苏省,苏州市",
    "厦门": "福建省,厦门市",
    "福州": "福建省,福州市",
    "青岛": "山东省,青岛市",
    "大连": "辽宁省,大连市",
    "沈阳": "辽宁省,沈阳市",
    "哈尔滨": "黑龙江省,哈尔滨市",
    "长春": "吉林省,长春市",
    "昆明": "云南省,昆明市",
    "贵阳": "贵州省,贵阳市",
    "南宁": "广西壮族自治区,南宁市",
    "海口": "海南省,海口市",
    "乌鲁木齐": "新疆维吾尔自治区,乌鲁木齐市",
    "拉萨": "西藏自治区,拉萨市",
    "银川": "宁夏回族自治区,银川市",
    "西宁": "青海省,西宁市",
    "兰州": "甘肃省,兰州市",
    "呼和浩特": "内蒙古自治区,呼和浩特市",
    "石家庄": "河北省,石家庄市",
    "太原": "山西省,太原市",
    "郑州": "河南省,郑州市",
    "济南": "山东省,济南市",
    "合肥": "安徽省,合肥市",
    "南昌": "江西省,南昌市",
    "长沙": "湖南省,长沙市",
}


@dataclass(frozen=True)
class MsnWeatherSnapshot:
    city: str
    line: str
    location: str = ""
    condition: str = ""
    temperature_c: int | None = None
    feels_like_c: int | None = None
    wind: str = ""
    horizon: str = "today"  # today | tomorrow
    tomorrow_high_c: int | None = None
    tomorrow_low_c: int | None = None
    tomorrow_hints: tuple[str, ...] = field(default_factory=tuple)
    rain_tomorrow: bool = False
    warning: str = ""

    @property
    def ok(self) -> bool:
        return bool((self.line or "").strip())


def _ensure_city_suffix(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    if raw.endswith(("省", "市", "区", "县", "自治区", "自治州")):
        return raw
    return f"{raw}市"


def msn_location_for_city(city: str) -> str:
    """将设置中的城市名转为 MSN URL 片段。"""
    raw = (city or "").strip()
    if not raw:
        return ""
    if "," in raw or "，" in raw:
        parts = re.split(r"[,，]", raw, maxsplit=1)
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""
        if left and right:
            return f"{_ensure_city_suffix(left)},{_ensure_city_suffix(right)}"
        return raw.replace("，", ",")
    key = raw.rstrip("市")
    mapped = _CITY_TO_MSN_LOC.get(key) or _CITY_TO_MSN_LOC.get(raw)
    if mapped:
        return mapped
    return _ensure_city_suffix(raw)


def msn_weather_url(city: str) -> str:
    loc = msn_location_for_city(city)
    if not loc:
        return ""
    return MSN_WEATHER_BASE + urllib.parse.quote(loc, safe="")


def _collect_conditions(scope: str) -> list[str]:
    """在片段中收集所有命中的天气词（长词优先，避免「多云」吞掉「大部多云」）。"""
    found: list[str] = []
    for word in sorted(_CONDITION_WORDS, key=len, reverse=True):
        if word not in scope:
            continue
        if any(word in other and word != other for other in found):
            continue
        found.append(word)
    return found


def _best_condition(candidates: list[str]) -> str:
    if not candidates:
        return ""
    return max(candidates, key=lambda w: _CONDITION_SEVERITY.get(w, 0))


def _parse_weather_warning(text: str) -> str:
    head = text[:5000]
    m = re.search(
        r"((?:暴雨|大雨|台风|雷电)[^。\n]{0,16}(?:黄|橙|红)色预警|(?:黄|橙|红)色预警[^。\n]{0,16}(?:暴雨|大雨))",
        head,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"(降雨将持续[^。\n]{0,40})", head)
    if m:
        return m.group(1).strip()
    return ""


def _parse_condition(text: str) -> str:
    """优先在「温度:N°」附近的实况区取天气，多命中时按 severity 取最重。"""
    temp_m = re.search(r"(?:^|\n)温度:(\d+)°", text, re.MULTILINE)
    if temp_m:
        # 常见布局：城市名 / 天气词 / 温度 —— 实况词通常在温度正上方
        prefix = text[: temp_m.start()]
        lines = [ln.strip() for ln in prefix.split("\n") if ln.strip()]
        for ln in reversed(lines[-4:]):
            if "预警" in ln or "降雨将持续" in ln:
                continue
            if ln in _CONDITION_WORDS:
                return ln
            hit = _collect_conditions(ln)
            if hit:
                return _best_condition(hit)

        start = max(0, temp_m.start() - 600)
        end = min(len(text), temp_m.end() + 400)
        window = text[start:end]
        # 排除预警行，避免「暴雨-橙色预警」盖过实况「大雨」
        window_lines = [
            ln for ln in window.split("\n") if "预警" not in ln and "降雨将持续" not in ln
        ]
        window = "\n".join(window_lines)
        scoped = _best_condition(_collect_conditions(window))
        if scoped:
            return scoped

    head = text[:1500]
    head_lines = [
        ln for ln in head.split("\n") if "预警" not in ln and "降雨将持续" not in ln
    ]
    scoped = _best_condition(_collect_conditions("\n".join(head_lines)))
    if scoped:
        return scoped

    warning = _parse_weather_warning(text)
    if warning and re.search(r"暴雨|大雨|降雨", warning):
        if "暴雨" in text[:3000]:
            return "暴雨"
        if "大雨" in text[:3000]:
            return "大雨"
        return "雨"
    return ""


def _tomorrow_weekday_label() -> str:
    tomorrow = datetime.now() + timedelta(days=1)
    return f"周{_WEEKDAY_ZH[tomorrow.weekday()]}"


def _parse_tomorrow_day_temps(lines: list[str]) -> tuple[int | None, int | None]:
    """从 MSN 逐日预报卡片解析明日最高/最低温。"""
    wd = _tomorrow_weekday_label()
    for i, ln in enumerate(lines):
        if ln != wd:
            continue
        nums: list[int] = []
        for j in range(i + 1, min(i + 5, len(lines))):
            m = re.fullmatch(r"(\d+)°", lines[j].strip())
            if m:
                nums.append(int(m.group(1)))
        if len(nums) >= 2:
            return nums[0], nums[1]
    return None, None


def _parse_tomorrow_hints(text: str) -> tuple[tuple[str, ...], bool]:
    hints: list[str] = []
    rain = False
    for m in re.finditer(r"(?:预计)?明天[^。\n]{0,80}", text):
        s = m.group(0).strip()
        if not s or s in hints:
            continue
        hints.append(s)
        if "雨" in s:
            rain = True
    if re.search(r"明天会有雨|预计明天会有雨", text):
        rain = True
    return tuple(hints[:5]), rain


def _build_tomorrow_line(
    *,
    city: str,
    high: int | None,
    low: int | None,
    hints: tuple[str, ...],
    rain: bool,
) -> str:
    wd = _tomorrow_weekday_label()
    parts = [f"{city} 明天（{wd}）"]
    if high is not None and low is not None:
        parts.append(f"气温{low}~{high}°C")
    elif high is not None:
        parts.append(f"最高约{high}°C")
    if rain:
        parts.append("可能有雨")
    elif hints:
        brief = hints[0]
        if "云" in brief:
            parts.append("多云为主")
        elif "类似" in brief or "差不多" in brief:
            parts.append("与今天相近")
        elif "冷" in brief:
            parts.append("比今天更凉")
        elif "暖" in brief:
            parts.append("比今天更暖")
    return "，".join(parts)


def _parse_page_text(*, text: str, title: str, city: str) -> MsnWeatherSnapshot:
    loc_m = re.search(r"^(.+?)\s+天气预报", title or "")
    location = loc_m.group(1).strip() if loc_m else ""
    feels_m = re.search(r"体感温度:(\d+)°", text)
    temp_m = re.search(r"(?:^|\n)温度:(\d+)°", text, re.MULTILINE)
    wind_m = re.search(r"([东南西北]{1,2}风)\s*(\d+)级", text)
    condition = _parse_condition(text)
    warning = _parse_weather_warning(text)

    temp = int(temp_m.group(1)) if temp_m else None
    feels = int(feels_m.group(1)) if feels_m else None
    wind = ""
    if wind_m:
        wind = f"{wind_m.group(1)}{wind_m.group(2)}级"

    display = (city or "").strip()
    if not display and location:
        display = location.split(",")[-1].strip()

    parts: list[str] = []
    if display and condition:
        parts.append(f"{display} {condition}")
    elif display:
        parts.append(display)
    elif condition:
        parts.append(condition)

    if temp is not None:
        parts.append(f"{temp}°C")
    if feels is not None:
        parts.append(f"体感{feels}°")
    if wind:
        parts.append(wind)
    if warning:
        parts.append(f"（{warning}）")

    line = "，".join(parts)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    t_high, t_low = _parse_tomorrow_day_temps(lines)
    t_hints, t_rain = _parse_tomorrow_hints(text)
    tomorrow_line = _build_tomorrow_line(
        city=display,
        high=t_high,
        low=t_low,
        hints=t_hints,
        rain=t_rain,
    )
    return MsnWeatherSnapshot(
        city=display,
        line=line,
        location=location,
        condition=condition,
        temperature_c=temp,
        feels_like_c=feels,
        wind=wind,
        tomorrow_high_c=t_high,
        tomorrow_low_c=t_low,
        tomorrow_hints=t_hints,
        rain_tomorrow=t_rain,
        warning=warning,
        horizon="today",
    )


def _snapshot_for_horizon(snap: MsnWeatherSnapshot, *, horizon: str) -> MsnWeatherSnapshot:
    if horizon != "tomorrow":
        return snap
    t_line = _build_tomorrow_line(
        city=snap.city,
        high=snap.tomorrow_high_c,
        low=snap.tomorrow_low_c,
        hints=snap.tomorrow_hints,
        rain=snap.rain_tomorrow,
    )
    if not t_line:
        return MsnWeatherSnapshot(city=snap.city, line="", horizon="tomorrow")
    return MsnWeatherSnapshot(
        city=snap.city,
        line=t_line,
        location=snap.location,
        condition=snap.condition,
        temperature_c=snap.tomorrow_high_c,
        feels_like_c=snap.tomorrow_low_c,
        wind=snap.wind,
        horizon="tomorrow",
        tomorrow_high_c=snap.tomorrow_high_c,
        tomorrow_low_c=snap.tomorrow_low_c,
        tomorrow_hints=snap.tomorrow_hints,
        rain_tomorrow=snap.rain_tomorrow,
    )


def _fetch_with_playwright(url: str, *, city: str, timeout_ms: int = 45000) -> MsnWeatherSnapshot:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(locale="zh-CN")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3500)
            text = page.inner_text("body")
            title = page.title()
        finally:
            browser.close()
    return _parse_page_text(text=text, title=title, city=city)


def fetch_msn_weather_snapshot(
    *,
    city: str = "",
    enabled: bool = True,
    force_refresh: bool = False,
    horizon: str = "today",
) -> MsnWeatherSnapshot:
    """抓取 MSN 天气（Playwright + Edge）。"""
    global _weather_cache, _snapshot_cache
    raw_city = (city or "").strip()
    hz = (horizon or "today").strip().lower()
    if hz not in ("today", "tomorrow"):
        hz = "today"
    if not enabled or not raw_city:
        return MsnWeatherSnapshot(city=raw_city, line="", horizon=hz)

    now = time.time()
    cache_city, cache_hz = _snapshot_cache[0]
    if (
        not force_refresh
        and _snapshot_cache[1] is not None
        and cache_city == raw_city
        and cache_hz == hz
        and now < _snapshot_cache[2]
    ):
        return _snapshot_cache[1]

    url = msn_weather_url(raw_city)
    if not url:
        return MsnWeatherSnapshot(city=raw_city, line="", horizon=hz)

    try:
        snap = _fetch_with_playwright(url, city=raw_city)
    except ImportError:
        logger.warning(
            "MSN 天气需要 playwright 包（%s）。请在桌宠使用的 Python 环境执行："
            "python -m pip install playwright",
            raw_city,
        )
        return MsnWeatherSnapshot(city=raw_city, line="", horizon=hz)
    except Exception as exc:
        logger.warning("MSN 天气 Playwright 抓取失败 (%s): %s", raw_city, exc)
        return MsnWeatherSnapshot(city=raw_city, line="", horizon=hz)

    out = _snapshot_for_horizon(snap, horizon=hz)
    if out.ok:
        _weather_cache = (out.line.strip(), now + _CACHE_TTL)
        _snapshot_cache = ((raw_city, hz), out, now + _CACHE_TTL)
        logger.info("[weather] MSN %s (%s): %s", raw_city, hz, out.line)
    return out


def fetch_msn_weather_line(
    *,
    city: str = "",
    enabled: bool = True,
    force_refresh: bool = False,
) -> str:
    """抓取 MSN 天气并返回单行摘要（供 presence / 天气问答注入）。"""
    snap = fetch_msn_weather_snapshot(
        city=city, enabled=enabled, force_refresh=force_refresh
    )
    return (snap.line or "").strip()
