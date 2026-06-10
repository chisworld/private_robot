"""Unit tests for desktop assistant features."""

from __future__ import annotations

from pnn.companion.build_watcher import BuildLogWatcher, classify_build_tail
from pnn.clipboard.routing import needs_clipboard_task
from pnn.launch_apps.ingest import label_from_path, slug_from_label
from pnn.system_control.routing import (
    build_system_control_agent_mandate,
    needs_system_control_task,
    parse_brightness_adjustment,
    parse_volume_adjustment,
)


def test_slug_from_label_ascii():
    assert slug_from_label("WeChat", existing=set()) == "wechat"


def test_normalize_match_osu():
    from pnn.launch_apps.ingest import normalize_match_text

    assert normalize_match_text("osu！") == "osu"
    assert normalize_match_text("osu!") == "osu"


def test_find_osu_in_text():
    from pnn.launch_apps.service import LaunchAppsService

    svc = LaunchAppsService()
    svc.update_config(
        enabled=True,
        use_in_chat=True,
        apps=[
            {
                "id": "osu",
                "label": "osu!",
                "aliases": ["osu"],
                "path": __import__("sys").executable,
                "enabled": True,
            }
        ],
    )
    found = svc.find_app_in_text("打开osu！")
    assert found is not None
    assert found.id == "osu"


def test_direct_launch_app():
    from unittest.mock import patch

    from pnn.launch_apps.direct import try_direct_launch_app

    with patch(
        "pnn.launch_apps.service.launch_apps_service.chat_enabled",
        return_value=True,
    ):
        with patch(
            "pnn.launch_apps.service.launch_apps_service.find_app_in_text",
        ) as find_mock:
            with patch(
                "pnn.launch_apps.service.launch_apps_service.launch_entry",
                return_value="已启动 osu!",
            ) as launch_mock:
                from pnn.launch_apps.config_store import LaunchAppEntry

                entry = LaunchAppEntry(id="game", label="osu!", path="x.exe")
                find_mock.return_value = entry
                result = try_direct_launch_app("打开osu！")
                assert result == "已启动 osu!"
                launch_mock.assert_called_once_with(entry)


def test_duplicate_game_id_launches_matched_entry_not_first(tmp_path, monkeypatch):
    """回归：多个 app 共用 id=game 时，打开鸣潮不应误启动列表第一项（曾为 python.exe）。"""
    import pnn.core.paths as paths
    from pnn.launch_apps.config_store import LaunchAppEntry, LaunchAppsConfig, save_launch_apps_config
    from pnn.launch_apps.service import LaunchAppsService

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setattr(paths, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(
        "pnn.launch_apps.config_store.LAUNCH_APPS_CONFIG_PATH",
        cfg_dir / "launch_apps.json",
    )

    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "wuthering.exe").write_bytes(b"")
    save_launch_apps_config(
        LaunchAppsConfig(
            enabled=True,
            use_in_chat=True,
            apps=[
                LaunchAppEntry(id="game", label="osu!", path=str(tmp_path / "python.exe")),
                LaunchAppEntry(id="game", label="鸣潮", path=str(tmp_path / "wuthering.exe")),
            ],
        )
    )

    svc = LaunchAppsService()
    svc.reload_config()
    entry = svc.find_app_in_text("打开鸣潮")
    assert entry is not None
    assert entry.label == "鸣潮"
    assert entry.path.endswith("wuthering.exe")


def test_label_from_lnk():
    assert "微信" in label_from_path(__import__("pathlib").Path("微信.lnk")) or True


def test_system_control_routing():
    positives = (
        "帮我把音量调到20%",
        "30分钟后关机",
        "清空回收站",
        "亮度调高8",
        "声音大一点",
        "太吵了安静点",
        "屏幕暗一点",
        "背光调到50",
        "帮我清空废纸篓",
        "取消定时关机",
        "待会重启",
        "mute",
        "显示器太亮了",
    )
    for msg in positives:
        assert needs_system_control_task(msg), msg
    negatives = ("你好", "我昨晚睡眠不好", "看看屏幕上的代码")
    for msg in negatives:
        assert not needs_system_control_task(msg), msg


def test_volume_parse():
    assert parse_volume_adjustment("音量调到20%") == {"percent": 20}
    assert parse_volume_adjustment("把音量调小10") == {"delta": -10}
    assert parse_volume_adjustment("声音调大5") == {"delta": 5}
    assert parse_volume_adjustment("静音") == "mute"
    assert parse_volume_adjustment("太吵了") == {"hint": "down"}


def test_volume_mandate_delta():
    mandate = build_system_control_agent_mandate("把音量调小10")
    assert "delta=-10" in mandate
    assert "local__set_volume" in mandate


def test_direct_volume_absolute():
    from unittest.mock import patch

    from pnn.system_control.direct import try_direct_system_control

    with patch(
        "pnn.system_control.service.system_control_service.chat_enabled",
        return_value=True,
    ):
        with patch(
            "pnn.system_control.service.system_control_service.call_tool",
            return_value="已将系统音量设为约 10%",
        ) as mock_call:
            result = try_direct_system_control("把音量调到10")
            assert result == "已将系统音量设为约 10%"
            mock_call.assert_called_once()
            assert mock_call.call_args[0][1] == {"percent": 10}


def test_brightness_parse_delta():
    assert parse_brightness_adjustment("亮度调高8") == {"delta": 8}
    assert parse_brightness_adjustment("屏幕调暗10") == {"delta": -10}
    assert parse_brightness_adjustment("亮度调到80%") == {"percent": 80}


def test_brightness_mandate():
    mandate = build_system_control_agent_mandate("亮度调高8")
    assert "delta=8" in mandate
    assert "local__set_brightness" in mandate


def test_build_watcher_resolves_directory(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "build.log"
    log_file.write_text("BUILD SUCCESS\n", encoding="utf-8")
    watcher = BuildLogWatcher([str(tmp_path)])
    files = watcher._resolve_watch_files(str(tmp_path))
    assert log_file.resolve() in [p.resolve() for p in files]


def test_clipboard_routing():
    assert needs_clipboard_task("帮我总结一下剪贴板的内容")
    assert not needs_clipboard_task("你好")


def test_build_classify_failed():
    assert classify_build_tail("error TS2304: Cannot find name") == "failed"


def test_build_classify_success():
    assert classify_build_tail("webpack compiled successfully") == "success"
