#!/usr/bin/env python3
"""TTS 端到端自测：启动 GPT-SoVITS → 切换角色模型 → 合成 WAV。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pnn.core.logging import setup_logging
from pnn.tts.probe import probe_http_server
from pnn.tts.service import tts_service


def wait_alive(timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_http_server(tts_service._config.server_url):
            return True
        time.sleep(2.0)
    return False


def main() -> int:
    setup_logging()
    cfg = tts_service.get_config()
    print("== config ==")
    for key in ("work_path", "gpt_model_path", "sovits_model_path", "ref_audio_path"):
        print(f"  {key}: {cfg.get(key)}")

    if not cfg.get("work_path") or not Path(str(cfg["work_path"])).is_dir():
        print(f"[FAIL] work_path 无效: {cfg.get('work_path')}")
        return 1
    for key in ("gpt_model_path", "sovits_model_path", "ref_audio_path"):
        path = cfg.get(key)
        if not path or not Path(str(path)).is_file():
            print(f"[FAIL] 缺少或无效: {key} -> {path}")
            return 1

    print("\n== boot GPT-SoVITS ==")
    result = tts_service.begin_start_server()
    print("  kick:", result)
    if not wait_alive():
        print("[FAIL] 180s 内 GPT-SoVITS 未就绪")
        print("  last_error:", tts_service._last_error)
        return 1
    print("[OK] GPT-SoVITS 在线")

    print("\n== synthesize ==")
    text = "こんにちは、テストです。"
    out = ROOT / "data" / "tts" / "output" / "e2e_test.wav"
    try:
        path = tts_service.synthesize(text, output_path=out)
    except Exception as exc:
        print(f"[FAIL] 合成失败: {exc}")
        return 1

    size = path.stat().st_size
    print(f"[OK] 输出: {path} ({size} bytes)")
    if size < 1000:
        print("[FAIL] WAV 文件过小")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
