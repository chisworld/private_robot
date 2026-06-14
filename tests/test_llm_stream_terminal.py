"""终端 LLM 流式小块输出。"""

from __future__ import annotations

import threading

from pnn.pet import console_log


def test_stream_emits_small_chunks(monkeypatch, capsys):
    monkeypatch.setenv("PET_LLM_STREAM", "line")
    monkeypatch.setenv("PET_LLM_STREAM_CHUNK", "4")
    monkeypatch.setenv("PET_LLM_STREAM_INTERVAL", "0")
    console_log.log_llm_stream_reset()

    console_log.log_llm_stream_update("你好世界")
    out = capsys.readouterr().out
    assert "[pet-llm] +" in out
    assert "你好" in out or "世界" in out

    console_log.log_llm_stream_finish("你好世界。")
    out2 = capsys.readouterr().out
    assert "[pet-llm] 回复:" in out2


def test_default_summary_skips_stream_chunks(monkeypatch, capsys):
    monkeypatch.delenv("PET_LLM_STREAM", raising=False)
    console_log.log_llm_stream_reset()
    console_log.log_llm_stream_update("哥哥はよく")
    assert capsys.readouterr().out == ""
    console_log.log_llm_stream_finish("哥哥はよく休みたい。")
    out = capsys.readouterr().out
    assert "[pet-llm] +" not in out
    assert "[pet-llm] 回复:" in out


def test_prefill_start_no_deadlock():
    console_log.log_llm_prefill_start(route="local_qwen")
    console_log.log_llm_prefill_start(route="local_qwen")
    console_log.log_llm_prefill_stop()


def test_prefill_stop_announces_first_token(capsys):
    console_log.log_llm_prefill_stop(got_token=True)
    out = capsys.readouterr().out
    assert out == ""
    stop = threading.Event()
    console_log._PREFILL_STOP = stop  # noqa: SLF001
    console_log.log_llm_prefill_stop(got_token=True)
    out2 = capsys.readouterr().out
    assert "首 token 已到" in out2


def test_voice_line_each_segment_shows_chinese(capsys):
    console_log.log_voice_line("soft", "晚上好，哥哥。", tts_source="こんばんは。")
    console_log.log_voice_line("soft", "我开始了哦。", tts_source="始めるね……")
    out = capsys.readouterr().out
    assert "晚上好，哥哥。" in out
    assert "我开始了哦。" in out
    assert out.count("→朗读:") == 2
