"""TTS 资源按角色分目录。"""

from __future__ import annotations

from pathlib import Path

from pnn.tts.character_layout import (
    default_tts_pack_settings,
    normalize_tts_pack_settings,
    relative_ref_audio_path,
    to_project_relative,
)
from pnn.characters.pack import TtsPackSettings


def test_default_paths_use_character_subdir() -> None:
    tts = default_tts_pack_settings("里想奈")
    assert tts.ref_audio_path == "data/tts/里想奈/reference.wav"
    assert tts.gpt_model_path.startswith("models/里想奈/")
    assert tts.gpt_model_path.endswith(".ckpt")
    assert tts.sovits_model_path.startswith("models/里想奈/")
    assert tts.sovits_model_path.endswith(".pth")


def test_normalize_absolute_to_relative(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pnn.tts.character_layout.PROJECT_ROOT",
        tmp_path,
    )
    wav = tmp_path / "data" / "tts" / "塞拉" / "reference.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"RIFF" + b"\x00" * 40)
    tts = TtsPackSettings(
        ref_audio_path=str(wav),
        prompt_text="hello",
        gpt_model_path=str(tmp_path / "models" / "character" / "塞拉" / "塞拉.ckpt"),
        sovits_model_path="",
    )
    out = normalize_tts_pack_settings(tts, "塞拉", fill_missing=False)
    assert out.ref_audio_path == relative_ref_audio_path("塞拉")
    assert out.prompt_text == "hello"


def test_to_project_relative() -> None:
    rel = to_project_relative(Path("data/tts/树里亚/reference.wav"))
    assert rel == "data/tts/树里亚/reference.wav"
