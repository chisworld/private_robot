"""桌宠 pipeline 忙碌态：防止 LLM/TTS 并发导致未响应。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pnn.pet.controller import PetController, _qthread_running


def _make_controller(**overrides) -> PetController:
    c = PetController.__new__(PetController)
    c._turn_pipeline_active = overrides.get("turn_pipeline_active", False)
    c._loading = overrides.get("loading", False)
    c._chat_worker = overrides.get("chat_worker", None)
    c._seg_texts = overrides.get("seg_texts", [])
    c._playback_active = overrides.get("playback_active", False)
    c._play_queue = overrides.get("play_queue", [])
    c._seg_synth = overrides.get("seg_synth", set())
    c._seg_play_idx = overrides.get("seg_play_idx", 0)
    c._live2d = MagicMock()
    c._stall_guard = MagicMock()
    c._stall_guard.stop = MagicMock()
    return c


def test_chat_pipeline_active_while_turn_pipeline():
    c = _make_controller(turn_pipeline_active=True)
    assert hasattr(c, "chat_pipeline_active")
    assert c.chat_pipeline_active()


def test_is_busy_not_true_for_turn_pipeline_only():
    c = _make_controller(turn_pipeline_active=True)
    assert not c.is_busy()


def test_is_busy_while_tts_pipeline_active():
    c = _make_controller(seg_texts=["一句"], seg_synth={0})
    assert c.is_busy()


def test_is_busy_when_idle():
    c = _make_controller()
    assert not c.is_busy()


def test_qthread_running_handles_deleted_worker():
    worker = MagicMock()
    worker.isRunning.side_effect = RuntimeError("deleted")
    assert not _qthread_running(worker)


def test_release_turn_loading_emits_false():
    c = _make_controller(loading=True)
    c.loading_changed = MagicMock()
    c._stall_guard = MagicMock()
    c._stall_guard.stop = MagicMock()
    c._release_turn_loading()
    assert c._loading is False
    c.loading_changed.emit.assert_called_once_with(False)


def test_start_llm_turn_skips_when_worker_running():
    worker = MagicMock()
    worker.isRunning.return_value = True
    c = _make_controller(chat_worker=worker)
    c._turn_id = 1
    c._stream_cancel = MagicMock()
    c._stream_cancel.clear = MagicMock()
    c._reset_tts_state = MagicMock()
    c.loading_changed = MagicMock()
    c._arm_stall_guard = MagicMock()
    c._emit_status = MagicMock()
    c._ensure_expression_catalog = MagicMock()
    c._merge_presence_prompt = MagicMock(return_value=None)
    c._api = MagicMock()
    c._stream_cancel = __import__("threading").Event()
    c._voice_output_enabled = False
    c.bubble_changed = MagicMock()
    c._delta_throttle = MagicMock()
    c._pet_expr_prompt = ""
    c._proactive_turn = False
    c._live2d = MagicMock()
    c._chat_worker = worker

    before = c._turn_pipeline_active
    c._start_llm_turn(
        "hi",
        history_snapshot=[],
        append_user_history=False,
    )
    assert c._turn_pipeline_active is before
