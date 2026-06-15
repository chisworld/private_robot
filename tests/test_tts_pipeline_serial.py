"""TTS 分句 pipeline：禁止播放中并发合成（第二句卡死根因）。"""

from __future__ import annotations

import io
import struct
import wave
from unittest.mock import MagicMock, patch

from pnn.pet.controller import PetController, _qthread_running


def _minimal_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        samples = struct.pack("<" + "h" * 512, *([8000] * 512))
        wf.writeframes(samples)
    return buf.getvalue()


def _make_tts_controller(**overrides) -> PetController:
    c = PetController.__new__(PetController)
    c._playback_active = overrides.get("playback_active", False)
    c._play_queue = overrides.get("play_queue", [])
    c._seg_texts = overrides.get("seg_texts", ["第一句", "第二句"])
    c._seg_play_idx = overrides.get("seg_play_idx", 0)
    c._seg_audio = overrides.get("seg_audio", {})
    c._seg_synth = overrides.get("seg_synth", set())
    c._seg_failed = overrides.get("seg_failed", set())
    c._seg_chunk_remain = overrides.get("seg_chunk_remain", {})
    c._tts_worker = overrides.get("tts_worker", None)
    c._turn_id = 1
    c._stream_cancel = __import__("threading").Event()
    c._live2d = MagicMock()
    c._api = MagicMock()
    return c


def test_pump_seg_synth_prefetches_next_during_playback():
    c = _make_tts_controller(
        playback_active=True,
        seg_play_idx=0,
        seg_audio={0: _minimal_wav()},
    )
    with patch.object(c, "_start_seg_synth") as start:
        c._pump_seg_synth()
        start.assert_called_once_with(1, "第二句")


def test_pump_seg_synth_skips_far_ahead_during_playback():
    c = _make_tts_controller(
        playback_active=True,
        seg_play_idx=0,
        seg_texts=["一", "二", "三"],
        seg_audio={0: _minimal_wav()},
    )
    with patch.object(c, "_start_seg_synth") as start:
        c._pump_seg_synth()
        start.assert_called_once_with(1, "二")


def test_pump_seg_synth_skips_when_worker_running():
    worker = MagicMock()
    worker.isRunning.return_value = True
    c = _make_tts_controller(tts_worker=worker)
    with patch.object(c, "_start_seg_synth") as start:
        c._pump_seg_synth()
        start.assert_not_called()


def test_pump_seg_synth_starts_first_pending_only():
    c = _make_tts_controller()
    started: list[int] = []

    def _fake_start(idx: int, text: str) -> None:
        started.append(idx)
        c._seg_synth.add(idx)

    with patch.object(c, "_start_seg_synth", side_effect=_fake_start):
        c._pump_seg_synth()
    assert started == [0]


def test_on_seg_synth_done_pumps_prefetch_during_playback():
    c = _make_tts_controller()
    c._playback_active = True
    c._pump_seg_play = MagicMock()
    c._pump_seg_synth = MagicMock()
    c._sync_pipeline_status = MagicMock()
    c._is_stale_turn = MagicMock(return_value=False)
    wav = _minimal_wav()
    c._on_seg_synth_done(0, [("子句", wav)], turn=1)
    c._pump_seg_play.assert_called_once()
    c._pump_seg_synth.assert_called_once()


def test_on_seg_play_ended_triggers_synth_for_next_segment():
    c = _make_tts_controller(
        seg_play_idx=0,
        seg_audio={0: _minimal_wav()},
    )
    c._pump_seg_synth = MagicMock()
    c._pump_seg_play = MagicMock()
    c._on_seg_play_ended()
    assert c._seg_play_idx == 1
    c._pump_seg_synth.assert_called_once()
    c._pump_seg_play.assert_called_once()


def test_tts_service_has_synth_lock():
    from pnn.tts.service import TtsService

    svc = TtsService()
    assert hasattr(svc, "_synth_lock")


def test_qthread_running_with_tts_worker():
    worker = MagicMock()
    worker.isRunning.return_value = False
    assert not _qthread_running(worker)
