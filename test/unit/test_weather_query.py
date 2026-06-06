from __future__ import annotations

from pnn.core.weather_query import (
    augment_user_message_prefix,
    build_weather_system_context,
    is_bad_weather_reply,
    sanitize_chat_history_for_weather,
    user_asks_saved_city,
    user_asks_weather,
    user_mentions_date_invite,
    weather_query_horizon,
)


def test_user_asks_weather_positive():
    assert user_asks_weather("帮我看看今天的天气情况")
    assert user_asks_weather("现在气温多少度")
    assert user_asks_weather("天気はどう？")


def test_user_asks_weather_negative():
    assert not user_asks_weather("今天天气不错")
    assert not user_asks_weather("")


def test_user_asks_saved_city():
    assert user_asks_saved_city("知道我们现在的城市在哪吗")
    assert user_asks_saved_city("我们在哪个城市")


def test_build_weather_context_injects_live_data(monkeypatch):
    monkeypatch.setattr(
        "pnn.core.weather_query.saved_weather_city",
        lambda: "温州",
    )
    monkeypatch.setattr(
        "pnn.core.weather_query.fetch_live_weather_for_saved_city",
        lambda **kw: type(
            "S",
            (),
            {"city": "温州", "line": "温州 晴，26°C，湿度60%", "ok": True, "source": "test"},
        )(),
    )
    ctx = build_weather_system_context("帮我看看今天的天气")
    assert ctx is not None
    assert "【内部天气·勿提来源】" in ctx
    assert "温州" in ctx
    assert "26°C" in ctx
    assert "【程序天气·回答规则】" in ctx
    assert "禁止编造" in ctx
    assert "MSN" in ctx
    assert "具体温度" in ctx or "数字" in ctx


def test_build_city_context(monkeypatch):
    monkeypatch.setattr(
        "pnn.core.weather_query.saved_weather_city",
        lambda: "温州",
    )
    ctx = build_weather_system_context("知道我们现在的城市在哪吗")
    assert ctx is not None
    assert "【程序定位】" in ctx
    assert "温州" in ctx


def test_build_weather_context_date_scene(monkeypatch):
    monkeypatch.setattr(
        "pnn.core.weather_query.saved_weather_city",
        lambda: "龙港",
    )
    monkeypatch.setattr(
        "pnn.core.weather_query.fetch_live_weather_for_saved_city",
        lambda **kw: type(
            "S",
            (),
            {"city": "龙港", "line": "龙港 明天 24~30°C", "ok": True, "source": "test"},
        )(),
    )
    ctx = build_weather_system_context("明天天气怎么样，我想和你去约会")
    assert ctx is not None
    assert "【天气场景】" in ctx
    assert "约会" in ctx
    assert "明天" in ctx
    assert "不要像天气预报员" in ctx
    assert user_mentions_date_invite("明天天气怎么样，我想和你去约会")
    assert user_mentions_date_invite("明天天气如何，我想和里想奈出去约会")


def test_augment_prefix_includes_weather_line(monkeypatch):
    monkeypatch.setattr(
        "pnn.core.weather_query.format_weather_user_prefix",
        lambda _msg: "[weather] city=温州; live=温州 晴，26°C",
    )
    out = augment_user_message_prefix("今天天气怎么样")
    assert "[clock]" not in out
    assert "[weather]" in out
    assert "[weather-reply]" in out
    assert "今天天气怎么样" in out


def test_augment_prefix_no_clock_on_casual_chat():
    out = augment_user_message_prefix("我喜欢吃红烧肉，韭菜炒蛋")
    assert "[clock]" not in out
    assert "我喜欢吃红烧肉" in out


def test_augment_prefix_includes_clock_when_asking_time():
    out = augment_user_message_prefix("现在几点了")
    assert "[clock]" in out
    assert "现在几点了" in out


def test_is_bad_weather_reply_detects_msn_broadcast():
    bad = "嗯，我已经在MSN上查过了。龙港的明天，大约24〜29度。"
    assert is_bad_weather_reply(bad)
    assert not is_bad_weather_reply("【表情:微笑】明日は暖かいから、お出かけしてもいいんじゃない？")


def test_sanitize_history_drops_bad_weather_assistant():
    hist = [
        {"role": "user", "content": "明天天气怎么样"},
        {"role": "assistant", "content": "嗯，我已经在MSN上查过了。龙港的明天，大约24〜29度。"},
    ]
    cleaned = sanitize_chat_history_for_weather(hist, "明天想和你约会，不知道天气怎么样")
    assert len(cleaned) == 1
    assert cleaned[0]["role"] == "user"


def test_date_invite_with_ni():
    assert user_mentions_date_invite("明天想和你约会，不知道天气怎么样")
    assert user_asks_weather("明天想和你约会，不知道天气怎么样")


def test_tomorrow_weather_detection():
    assert user_asks_weather("明天天气怎么样啊，适合出去玩吗")
    assert weather_query_horizon("明天天气怎么样啊，适合出去玩吗") == "tomorrow"
    assert user_asks_weather("去查看明天天气怎么样，怎么没有查看天气")
    assert user_asks_weather("明天天气适合郊游吗")
    assert user_asks_weather("查看明天天气")
    assert user_asks_weather("明天天气怎么样，我想和你去约会")
