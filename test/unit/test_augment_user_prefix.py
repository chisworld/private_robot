from __future__ import annotations

from pnn.core.weather_query import augment_user_message_prefix


def test_augment_always_includes_clock():
    out = augment_user_message_prefix("今天天气不错")
    assert out.startswith("[clock]")
    assert "今天天气不错" in out
