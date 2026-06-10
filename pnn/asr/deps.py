"""ASR 运行时依赖（faster-whisper / sounddevice）。"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]


def preferred_python() -> str:
    venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


_ASR_PACKAGES: tuple[tuple[str, str], ...] = (
    ("faster_whisper", "faster-whisper>=1.1.0"),
    ("sounddevice", "sounddevice>=0.5.0"),
    ("numpy", "numpy>=1.24.0"),
)


def missing_asr_modules() -> list[str]:
    return [pip for mod, pip in _ASR_PACKAGES if importlib.util.find_spec(mod) is None]


def ensure_asr_runtime_deps(*, auto_install: bool = True) -> bool:
    missing = missing_asr_modules()
    if not missing:
        return True
    if not auto_install:
        return False
    logger.warning("缺少 ASR 依赖 %s，正在安装…", ", ".join(missing))
    try:
        subprocess.check_call(
            [preferred_python(), "-m", "pip", "install", *missing],
            cwd=str(_ROOT),
        )
    except subprocess.CalledProcessError:
        logger.error(
            "无法安装 ASR 依赖。请在项目目录运行: %s -m pip install -r requirements.txt",
            preferred_python(),
        )
        return False
    still = missing_asr_modules()
    if still:
        logger.error("安装后仍缺少: %s", ", ".join(still))
        return False
    return True


def asr_import_error_hint(exc: BaseException) -> str:
    msg = str(exc).strip() or type(exc).__name__
    if "faster_whisper" in msg or "No module named" in msg:
        py = preferred_python()
        return (
            "语音识别依赖未安装。"
            f"请在命令行执行:\n  \"{py}\" -m pip install faster-whisper sounddevice\n"
            "安装完成后重启 API（关闭桌宠再开，或结束 8765 端口进程）。"
        )
    return f"模型加载失败：{msg}"
