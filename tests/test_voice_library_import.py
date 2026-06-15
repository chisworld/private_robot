"""语音库导入：mp3 文件名解析与转 wav。"""

from __future__ import annotations

from pathlib import Path

from pnn.core.paths import PROJECT_ROOT
from pnn.tts.voice_library import (
    convert_audio_to_wav,
    import_voice_library,
    parse_ref_audio_filename,
    resolve_tts_emotion_tag,
    scan_voice_clips,
)


def test_parse_ref_audio_filename_accepts_mp3():
    clip = parse_ref_audio_filename("[sex]テスト参考文.mp3")
    assert clip is not None
    assert clip.tag_id == "sex"
    assert clip.prompt_text == "テスト参考文"


def test_scan_voice_clips_prefers_wav_over_mp3(tmp_path):
    (tmp_path / "[demo]wav版.wav").write_bytes(b"RIFF")
    (tmp_path / "[demo]mp3版.mp3").write_bytes(b"ID3")
    clips = scan_voice_clips(tmp_path)
    assert len(clips) == 1
    assert clips[0].tag_id == "demo"
    assert clips[0].source_wav.suffix.lower() == ".wav"


def test_convert_sex_mp3_to_wav(tmp_path):
    src_dir = PROJECT_ROOT / "models" / "里想奈"
    mp3s = list(src_dir.glob("[sex]*.mp3"))
    if not mp3s:
        return
    dest = tmp_path / "sex.wav"
    convert_audio_to_wav(mp3s[0], dest)
    assert dest.is_file()
    assert dest.stat().st_size > 1000


def test_import_resona_includes_sex_and_well_behaved():
    src_dir = PROJECT_ROOT / "models" / "里想奈"
    if not src_dir.is_dir():
        return
    manifest = import_voice_library("里想奈")
    ids = {p["id"] for p in manifest.presets}
    assert "sex" in ids
    assert "well-behaved" in ids
    assert resolve_tts_emotion_tag("亲密", "里想奈") == "sex"
    assert resolve_tts_emotion_tag("乖巧", "里想奈") == "well-behaved"
    sex = next(p for p in manifest.presets if p["id"] == "sex")
    ref = PROJECT_ROOT / sex["ref_audio_path"]
    assert ref.suffix.lower() == ".wav"
    assert ref.is_file()
