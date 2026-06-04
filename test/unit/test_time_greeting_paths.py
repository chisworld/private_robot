"""时段问候按角色分目录。"""

from __future__ import annotations

from pathlib import Path

from pnn.pet import time_greeting as tg


def test_wav_path_under_character_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tg, "TIME_GREETING_DIR", tmp_path)
    p = tg.time_greeting_wav_path("morning", "ja", char_id="里想奈")
    assert p == tmp_path / "里想奈" / "time_greeting_morning_ja.wav"


def test_resolve_prefers_character_over_flat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tg, "TIME_GREETING_DIR", tmp_path)
    flat = tmp_path / "time_greeting_noon_zh.wav"
    flat.write_bytes(b"\x00" * 100)
    char_dir = tmp_path / "塞拉"
    char_dir.mkdir()
    char_wav = char_dir / "time_greeting_noon_zh.wav"
    char_wav.write_bytes(b"\x00" * 200)
    got = tg.resolve_time_greeting_wav_path("noon", "zh", char_id="塞拉")
    assert got == char_wav


def test_migrate_flat_to_sera(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tg, "TIME_GREETING_DIR", tmp_path)
    src = tmp_path / "time_greeting_evening_ja.wav"
    src.write_bytes(b"RIFF" + b"\x00" * 40)
    n = tg.migrate_flat_assets_to_character("塞拉")
    assert n == 1
    assert not src.is_file()
    assert (tmp_path / "塞拉" / "time_greeting_evening_ja.wav").is_file()
