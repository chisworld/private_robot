"""配置读盘缓存、角色列表缓存、日志尾部读取。"""

from __future__ import annotations

from pathlib import Path

from pnn.core.config_cache import MtimeJsonConfigCache
from pnn.core.file_tail import read_tail_text
from pnn.llm import character_store
from pnn.llm.character_store import list_characters
from pnn.asr import devices as asr_devices
from pnn.asr.devices import list_input_devices
from pnn.memory.config_store import (
    MemoryConfig,
    load_memory_config,
    save_memory_config,
)
from pnn.launch_apps.config_store import (
    LaunchAppsConfig,
    load_launch_apps_config,
    save_launch_apps_config,
)
from pnn.mcp.config_store import McpConfig, load_mcp_config, save_mcp_config
from pnn.system_control.config_store import (
    SystemControlConfig,
    load_system_control_config,
    save_system_control_config,
)


def test_mtime_config_cache_reuses_until_save(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "memory.json"
    monkeypatch.setattr(
        "pnn.memory.config_store.MEMORY_CONFIG_PATH",
        cfg_path,
    )
    cache = MtimeJsonConfigCache[MemoryConfig]()
    cfg_path.write_text('{"top_k": 7}', encoding="utf-8")

    first = cache.get(cfg_path, load_memory_config)
    second = cache.get(cfg_path, load_memory_config)
    assert first.top_k == 7
    assert second.top_k == 7
    assert first is not second

    save_memory_config(MemoryConfig(top_k=9))
    third = cache.get(cfg_path, load_memory_config)
    assert third.top_k == 9


def test_list_characters_uses_cache(monkeypatch) -> None:
    character_store.invalidate_character_list_cache()
    calls = {"n": 0}

    def _fake_build() -> list[dict[str, str]]:
        calls["n"] += 1
        return [{"id": "demo", "name": "Demo"}]

    monkeypatch.setattr(character_store, "_build_character_list", _fake_build)
    assert list_characters() == [{"id": "demo", "name": "Demo"}]
    assert list_characters() == [{"id": "demo", "name": "Demo"}]
    assert calls["n"] == 1


def test_mcp_config_cache_reuses_until_save(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "mcp.json"
    monkeypatch.setattr("pnn.mcp.config_store.MCP_CONFIG_PATH", cfg_path)
    monkeypatch.setattr("pnn.mcp.config_store._ensure_config_file", lambda: None)
    cfg_path.write_text(
        '{"enabled": true, "use_in_chat": true, "max_agent_steps": 9, "servers": []}',
        encoding="utf-8",
    )

    first = load_mcp_config()
    second = load_mcp_config()
    assert first.max_agent_steps == 9
    assert second.max_agent_steps == 9
    assert first is not second

    save_mcp_config(McpConfig(max_agent_steps=11, servers=[]))
    third = load_mcp_config()
    assert third.max_agent_steps == 11


def test_launch_apps_config_cache_reuses_until_save(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "launch_apps.json"
    monkeypatch.setattr("pnn.launch_apps.config_store.LAUNCH_APPS_CONFIG_PATH", cfg_path)
    cfg_path.write_text('{"enabled": true, "use_in_chat": true, "apps": []}', encoding="utf-8")

    first = load_launch_apps_config()
    second = load_launch_apps_config()
    assert first.enabled is True
    assert second.enabled is True
    assert first is not second

    save_launch_apps_config(LaunchAppsConfig(enabled=False, apps=[]))
    third = load_launch_apps_config()
    assert third.enabled is False


def test_system_control_config_cache_reuses_until_save(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "system_control.json"
    monkeypatch.setattr("pnn.system_control.config_store.SYSTEM_CONTROL_CONFIG_PATH", cfg_path)
    cfg_path.write_text('{"enabled": true, "shutdown_confirm_minutes": 8}', encoding="utf-8")

    first = load_system_control_config()
    second = load_system_control_config()
    assert first.shutdown_confirm_minutes == 8
    assert second.shutdown_confirm_minutes == 8
    assert first is not second

    save_system_control_config(SystemControlConfig(shutdown_confirm_minutes=15))
    third = load_system_control_config()
    assert third.shutdown_confirm_minutes == 15


def test_asr_devices_cache_ttl(monkeypatch) -> None:
    asr_devices.invalidate_input_devices_cache()
    calls = {"n": 0}

    def _fake_list() -> list[dict[str, str]]:
        calls["n"] += 1
        return [{"id": 0, "name": "Mic", "hostapi": "WASAPI", "is_default": True}]

    monkeypatch.setattr(asr_devices, "_list_input_devices_uncached", _fake_list)
    assert list_input_devices() == [
        {"id": 0, "name": "Mic", "hostapi": "WASAPI", "is_default": True}
    ]
    assert list_input_devices() == [
        {"id": 0, "name": "Mic", "hostapi": "WASAPI", "is_default": True}
    ]
    assert calls["n"] == 1
    assert list_input_devices(force_refresh=True)[0]["name"] == "Mic"
    assert calls["n"] == 2


def test_read_tail_text_only_reads_end(tmp_path: Path) -> None:
    log_path = tmp_path / "api_boot.log"
    lines = [f"line-{i}" for i in range(200)]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tail = read_tail_text(log_path, max_lines=3)
    assert tail == "line-197\nline-198\nline-199"
