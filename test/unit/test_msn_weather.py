from __future__ import annotations

from pnn.core.msn_weather import _parse_page_text

# 模拟 MSN/Bing 页面：实况区「大雨」，逐日卡片含「大部多云」
_SAMPLE_LONGGANG_RAIN = """
浙江省温州市龙港市 天气预报
龙港
大雨
温度:25°
体感温度:28°
东北风 1级
今日最高 30° 最低 23°
降雨将持续至少 2 小时
暴雨 - 橙色预警
周日
30°
23°
大部多云
周一
28°
22°
多云
"""


def test_parse_current_rain_not_weekly_cloudy():
    snap = _parse_page_text(
        text=_SAMPLE_LONGGANG_RAIN,
        title="浙江省温州市龙港市 天气预报",
        city="龙港",
    )
    assert snap.condition == "大雨"
    assert snap.temperature_c == 25
    assert "大部多云" not in snap.line.split("，")[0]
    assert "25°C" in snap.line
    assert "大雨" in snap.line
    assert snap.warning


def test_parse_cloudy_when_no_rain():
    text = """
杭州
晴朗
温度:26°
体感温度:27°
东南风 2级
"""
    snap = _parse_page_text(text=text, title="浙江省杭州市 天气预报", city="杭州")
    assert snap.condition in ("晴朗", "晴")
    assert snap.temperature_c == 26
