"""新增功能轻量测试（不启动 TTS / 完整 API lifespan）。"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

from pnn.characters.pack import CharacterPack, save_pack
from pnn.characters.pack_io import export_character_pack_zip, import_character_pack_zip
from pnn.launch_apps.service import LaunchAppsService
from pnn.memory.service import memory_service
from pnn.pet.reminders.auto_trigger import build_reminder_trigger_text
from pnn.pet.reminders.from_chat import try_create_reminder_from_user_message
from pnn.pet.reminders.manager import session_key_from_character
from pnn.pet.reminders.models import Reminder


def test_launch_apps_local_tools_and_fail_notify():
    svc = LaunchAppsService()
    calls: list[tuple[str, str]] = []
    svc.register_fail_notifier(lambda k, m: calls.append((k, m)))
    svc.update_config(
        apps=[{"id": "qq", "label": "QQ", "path": "C:/fake/qq.exe", "enabled": True}],
        folders=[{"id": "dl", "label": "下载", "path": "C:/Users", "enabled": True}],
        urls=[{"id": "bili", "label": "B站", "url": "https://www.bilibili.com", "enabled": True}],
    )
    specs = svc.list_tool_specs()
    names = {s["name"] for s in specs}
    assert {"launch_app", "open_folder", "open_url"} <= names

    result = svc.call_launch_app({"app": "missing"})
    assert "未找到" in result
    assert calls and "失败" in calls[0][0]

    assert svc._normalize_whitelist_url("ftp://evil.com") == ""


def test_reminder_launch_app_trigger_text():
    r = Reminder(
        title="煮饭",
        scheduled_start=datetime(2026, 6, 7, 12, 0),
        launch_app_id="qq",
    )
    text = build_reminder_trigger_text(r, "due_start")
    assert "关联快捷启动" in text
    assert "自动" in text


def test_find_app_in_text():
    svc = LaunchAppsService()
    svc.update_config(
        apps=[
            {
                "id": "wuthering",
                "label": "鸣潮",
                "aliases": ["Wuthering Waves"],
                "path": "C:/fake/wuwa.exe",
                "enabled": True,
            }
        ],
    )
    app = svc.find_app_in_text("今天五点提醒我玩鸣潮")
    assert app is not None
    assert app.id == "wuthering"


def test_create_reminder_binds_launch_app(isolated_presence_data, monkeypatch):
    from pnn.launch_apps import service as launch_mod

    svc = LaunchAppsService()
    svc.update_config(
        apps=[
            {
                "id": "wuthering",
                "label": "鸣潮",
                "path": "C:/fake/wuwa.exe",
                "enabled": True,
            }
        ],
    )
    monkeypatch.setattr(launch_mod, "launch_apps_service", svc)

    sk = session_key_from_character("test")
    now = datetime(2026, 6, 7, 16, 0, 0)
    rem = try_create_reminder_from_user_message(
        sk,
        "今天五点提醒我玩鸣潮",
        now=now,
    )
    assert rem is not None
    assert rem.launch_app_id == "wuthering"
    assert rem.scheduled_start.hour == 17


def test_memory_list_filter():
    items = memory_service.list_memories(10, q="__unlikely_no_match__")
    assert items == []


def test_character_pack_zip_roundtrip(tmp_path, monkeypatch):
    import pnn.characters.pack as pack_mod
    import pnn.tts.character_layout as layout

    chars_root = tmp_path / "data" / "characters"
    tts_root = tmp_path / "data" / "tts"
    chars_root.mkdir(parents=True)
    tts_root.mkdir(parents=True)
    monkeypatch.setattr(pack_mod, "CHARACTERS_ROOT", chars_root)
    monkeypatch.setattr(layout, "CHARACTER_TTS_ROOT", tts_root)

    pack = CharacterPack(id="测试角色", name="测试", character_prompt="hi")
    save_pack(pack)
    tts_dir = tts_root / "测试角色"
    tts_dir.mkdir(parents=True, exist_ok=True)
    (tts_dir / "reference.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (tts_dir / "prompt.txt").write_text("prompt", encoding="utf-8")

    blob = export_character_pack_zip("测试角色")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert "pack.json" in zf.namelist()
        assert "manifest.json" in zf.namelist()

    imported = import_character_pack_zip(blob, new_id="测试角色2", overwrite=True)
    assert imported.id == "测试角色2"
    assert (chars_root / "测试角色2" / "pack.json").is_file()
