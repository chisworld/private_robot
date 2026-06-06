from __future__ import annotations

from pnn.core.msn_weather import (
    _parse_page_text,
    msn_location_for_city,
    msn_weather_url,
)


def test_msn_location_for_city_longgang():
    assert msn_location_for_city("龙港") == "浙江省,龙港市"


def test_msn_location_for_city_wenzhou():
    assert msn_location_for_city("温州") == "浙江省,温州市"
    url = msn_weather_url("温州")
    assert url.startswith("https://www.msn.cn/zh-cn/weather/forecast/in-")
    assert "%E6%B5%99%E6%B1%9F%E7%9C%81" in url
    assert "%E6%B8%A9%E5%B7%9E%E5%B8%82" in url


def test_msn_location_custom_pair():
    assert msn_location_for_city("浙江省,温州") == "浙江省,温州市"


def test_parse_msn_page_text():
    text = (
        "浙江省, 温州市\n"
        "多云\n"
        "东南风 1级\n"
        "体感温度:27°\n"
        "温度:26°\n"
    )
    snap = _parse_page_text(
        text=text,
        title="浙江省, 温州市 天气预报 | MSN 天气",
        city="温州",
    )
    assert snap.ok
    assert "26°C" in snap.line
    assert "多云" in snap.line
    assert "体感27°" in snap.line
    assert "东南风1级" in snap.line
