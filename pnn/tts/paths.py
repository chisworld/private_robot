from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

from pnn.core.paths import (
    PROJECT_ROOT,
    TTS_MODELS_ROOT,
    _GPT_SOVITS_DIRNAME,
    _resolve_existing_dir,
    resolve_gpt_sovits_bundle,
)

GPT_SOVITS_BUNDLE = TTS_MODELS_ROOT / _GPT_SOVITS_DIRNAME
GPT_SOVITS_ROOT = GPT_SOVITS_BUNDLE
TTS_CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "tts.json"

from pnn.tts.character_layout import LEGACY_REFERENCE_DIR as TTS_REFERENCE_DIR  # noqa: E402


def _bundle_from_base(base: Path) -> Path | None:
    if (base / "api_v2.py").is_file() and (base / "runtime" / "python.exe").is_file():
        return base.resolve()
    if base.is_dir():
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            if (child / "api_v2.py").is_file() and (child / "runtime" / "python.exe").is_file():
                return child.resolve()
    return None


def _conda_ai_python() -> Path | None:
    """与 launch/start_pet.bat 一致：优先使用 conda 环境 AI。"""
    home = Path.home()
    for rel in (
        "anaconda3/envs/AI/python.exe",
        "miniconda3/envs/AI/python.exe",
    ):
        candidate = home / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate.resolve()
    return None


def _gpt_sovits_python_ok(python: Path, *, timeout: float = 15.0) -> bool:
    """整合包 api_v2 至少需要 soundfile / fastapi / uvicorn。"""
    try:
        proc = subprocess.run(
            [
                str(python),
                "-c",
                "import soundfile, fastapi, uvicorn",
            ],
            capture_output=True,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def resolve_gpt_sovits_python(
    work_path: str | Path,
    python_path: str | None = None,
) -> Path:
    """
    解析用于启动 api_v2.py 的解释器。
    顺序：tts.json 的 python_path → 整合包 runtime/python.exe（自带依赖）
    → conda 环境 AI（须已安装 soundfile 等，否则会跳过）。
    """
    if python_path and str(python_path).strip():
        explicit = Path(str(python_path).strip())
        if not explicit.is_file():
            raise FileNotFoundError(f"配置的 python_path 不存在: {explicit}")
        resolved = explicit.resolve()
        if not _gpt_sovits_python_ok(resolved):
            raise RuntimeError(
                f"python_path 缺少 GPT-SoVITS 依赖（soundfile 等）: {resolved}\n"
                "可在该环境执行: pip install soundfile fastapi uvicorn"
            )
        return resolved

    embedded = Path(work_path) / "runtime" / "python.exe"
    if embedded.is_file():
        return embedded.resolve()

    conda_py = _conda_ai_python()
    if conda_py is not None and _gpt_sovits_python_ok(conda_py):
        logger.info("GPT-SoVITS 使用 conda 环境 AI: %s", conda_py)
        return conda_py
    if conda_py is not None:
        logger.warning(
            "conda 环境 AI 缺少 GPT-SoVITS 依赖，已回退整合包 runtime。"
            "若要用 conda 启动，请执行: pip install soundfile fastapi uvicorn"
        )

    raise FileNotFoundError(
        f"未找到可用的 GPT-SoVITS Python：请保留 {embedded}，"
        "或在 tts.json 配置已装好依赖的 python_path"
    )


def resolve_gpt_sovits_work_path(path: str | Path | None = None) -> Path | None:
    """解析 GPT-SoVITS 整合包根目录（含 api_v2.py 与 runtime/python.exe）。"""
    if path:
        raw = Path(path)
        base = _resolve_existing_dir(raw)
        if base is not None:
            found = _bundle_from_base(base)
            if found is not None:
                return found
    return resolve_gpt_sovits_bundle()


def default_gpt_sovits_models(bundle: Path) -> tuple[str, str]:
    """返回 v2Pro 默认 GPT / SoVITS 权重路径。"""
    gpt = bundle / "GPT_SoVITS" / "pretrained_models" / "s1v3.ckpt"
    sovits = bundle / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth"
    if not gpt.is_file():
        gpt = (
            bundle
            / "GPT_SoVITS"
            / "pretrained_models"
            / "gsv-v2final-pretrained"
            / "s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt"
        )
    if not sovits.is_file():
        sovits = (
            bundle
            / "GPT_SoVITS"
            / "pretrained_models"
            / "gsv-v2final-pretrained"
            / "s2Gv2.pth"
        )
    return str(gpt.resolve()), str(sovits.resolve())
