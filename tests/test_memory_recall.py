"""记忆：时间标签与回忆式重复提取防护。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pnn.memory.recall_guard import is_recall_only_extraction
from pnn.memory.time_label import format_memory_line, memory_age_label


def test_memory_age_label_yesterday():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    label = memory_age_label(yesterday.isoformat())
    assert label == "昨天"


def test_format_memory_line_includes_age():
    ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    line = format_memory_line(kind="event", content="哥哥被毒蛙咬伤", created_at=ts)
    assert "昨天" in line
    assert "毒蛙" in line


def test_recall_only_when_user_says_shower_only():
    user = "我要去洗澡了"
    assistant = "哥哥要洗澡了？今天不是被毒蛙咬了吗，伤口别碰水。"
    extracted = "哥哥被毒蛙咬了，里想奈很担心"
    assert is_recall_only_extraction(user, assistant, extracted)


def test_not_recall_when_user_asks_about_frog():
    user = "昨天被毒蛙咬的伤口还疼吗"
    assistant = "让我看看…还红肿的话要去医院。"
    extracted = "哥哥昨天被毒蛙咬伤"
    assert not is_recall_only_extraction(user, assistant, extracted)
