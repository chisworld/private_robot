from __future__ import annotations

from pnn.asr.devices import format_mic_open_error


def test_format_mic_open_error_permission_hint():
    msg = format_mic_open_error(RuntimeError("Permission denied"), None)
    assert "麦克风" in msg
    assert "隐私" in msg or "无法打开" in msg
