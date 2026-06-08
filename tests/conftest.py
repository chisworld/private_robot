"""presence / reminders 测试隔离：使用临时 data 目录。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_presence_data(tmp_path, monkeypatch):
    """将 presence / reminders / config 重定向到临时目录。"""
    data = tmp_path / "data"
    cfg = data / "config"
    cfg.mkdir(parents=True)
    (data / "presence").mkdir()
    (data / "presence" / "pomodoro").mkdir()
    (data / "presence" / "daily_log").mkdir()
    (data / "reminders").mkdir()

    import pnn.core.paths as paths

    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", cfg)

    import pnn.pet.presence.store as pstore
    import pnn.pet.reminders.store as rstore

    monkeypatch.setattr(pstore, "_PRESENCE_DIR", data / "presence")
    monkeypatch.setattr(rstore, "_DEFAULT_PATH", data / "reminders" / "reminders.json")

    # 重置单例，避免跨用例污染
    import pnn.pet.presence.service as psvc
    import pnn.pet.reminders.manager as rmgr

    monkeypatch.setattr(psvc, "_singleton", None)
    monkeypatch.setattr(rmgr, "_singleton", None)

    return data
