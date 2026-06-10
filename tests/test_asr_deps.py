from __future__ import annotations

from pnn.asr.deps import asr_import_error_hint, missing_asr_modules


def test_missing_asr_modules_detects_faster_whisper_name():
    # faster_whisper should be present in dev env; hint text is stable
    hint = asr_import_error_hint(ImportError("No module named 'faster_whisper'"))
    assert "faster-whisper" in hint
    assert "pip install" in hint
