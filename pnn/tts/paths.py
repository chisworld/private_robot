from __future__ import annotations

from pathlib import Path

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
TTS_REFERENCE_DIR = PROJECT_ROOT / "data" / "tts" / "reference"


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
