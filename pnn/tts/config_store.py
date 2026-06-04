from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pnn.core.env import load_env

from pnn.core.paths import PROJECT_ROOT
from pnn.tts.character_layout import (
    LEGACY_REFERENCE_DIR,
    active_character_id,
    character_reference_wav,
    read_prompt_text,
)
from pnn.tts.paths import (
    TTS_CONFIG_PATH,
    default_gpt_sovits_models,
    resolve_gpt_sovits_work_path,
)

# 兼容旧 import
TTS_REFERENCE_DIR = LEGACY_REFERENCE_DIR


def resolve_model_file_path(path: str) -> str:
    """将 models/character/... 等相对路径解析为绝对路径（供 GPT-SoVITS API 使用）。"""
    raw = (path or "").strip()
    if not raw:
        return raw
    candidate = Path(raw)
    if candidate.is_file():
        return str(candidate.resolve())
    rooted = PROJECT_ROOT / raw
    if rooted.is_file():
        return str(rooted.resolve())
    return raw

if TYPE_CHECKING:
    from pnn.tts.service import TtsConfig

logger = logging.getLogger(__name__)

REF_PROMPT_TEXT = "欢迎大家来体验达摩院推出的语音识别模型。"


def _env_overrides() -> dict[str, Any]:
    load_env()
    out: dict[str, Any] = {}
    key = os.getenv("TTS_API_KEY", "").strip()
    if key:
        out["api_key"] = key
    url = os.getenv("TTS_SERVER_URL", "").strip()
    if url:
        out["server_url"] = url.rstrip("/")
    return out


def _apply_env_overrides(config: TtsConfig) -> TtsConfig:
    for key, value in _env_overrides().items():
        if hasattr(config, key) and value:
            setattr(config, key, value)
    return config


def mirror_reference_audio(ref_path: str, *, char_id: str | None = None) -> str:
    from pnn.tts.ref_audio import mirror_reference_audio as _mirror

    return _mirror(ref_path, char_id=char_id)


def apply_bundle_defaults(config: TtsConfig) -> None:
    bundle = resolve_gpt_sovits_work_path(config.work_path)
    if bundle is None:
        return

    config.work_path = str(bundle)

    if config.gpt_model_path:
        config.gpt_model_path = resolve_model_file_path(config.gpt_model_path)
    if config.sovits_model_path:
        config.sovits_model_path = resolve_model_file_path(config.sovits_model_path)

    gpt, sovits = default_gpt_sovits_models(bundle)
    if not config.gpt_model_path or not Path(config.gpt_model_path).is_file():
        if Path(gpt).is_file():
            config.gpt_model_path = gpt
    if not config.sovits_model_path or not Path(config.sovits_model_path).is_file():
        if Path(sovits).is_file():
            config.sovits_model_path = sovits

    cid = active_character_id()
    if config.ref_audio_path and Path(config.ref_audio_path).is_file():
        config.ref_audio_path = mirror_reference_audio(config.ref_audio_path, char_id=cid)
    elif not config.ref_audio_path or not Path(config.ref_audio_path).is_file():
        ref_path, ref_text = ensure_reference_audio(bundle, char_id=cid)
        if ref_path:
            config.ref_audio_path = ref_path
            if not config.prompt_text:
                config.prompt_text = ref_text
    if not (config.prompt_text or "").strip():
        stored = read_prompt_text(cid)
        if stored:
            config.prompt_text = stored


def ensure_reference_audio(bundle: Path, *, char_id: str | None = None) -> tuple[str, str]:
    cid = char_id or active_character_id()
    local = character_reference_wav(cid)
    if local.is_file():
        return str(local.resolve()), read_prompt_text(cid) or REF_PROMPT_TEXT
    legacy = LEGACY_REFERENCE_DIR / "ref_zh.wav"
    if legacy.is_file():
        return str(legacy.resolve()), REF_PROMPT_TEXT

    bundled = (
        bundle
        / "tools"
        / "asr"
        / "models"
        / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        / "example"
        / "asr_example.wav"
    )
    if not bundled.is_file():
        return "", ""

    local.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundled, local)
    logger.info("已复制默认参考音频 [%s]: %s", cid, local)
    return str(local.resolve()), REF_PROMPT_TEXT


def build_default_config() -> TtsConfig:
    from pnn.tts.service import TtsConfig

    config = TtsConfig(
        provider="gpt-sovits",
        server_url="http://127.0.0.1:9880",
        work_path=str(resolve_gpt_sovits_work_path() or ""),
        prompt_lang="zh",
        text_lang="zh",
        speed_factor=1.0,
        auto_start_server=True,
    )
    apply_bundle_defaults(config)
    return _apply_env_overrides(config)


def load_tts_config() -> TtsConfig:
    from pnn.tts.service import TtsConfig

    if not TTS_CONFIG_PATH.is_file():
        config = build_default_config()
        save_tts_config(config)
        return config

    try:
        raw = json.loads(TTS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 TTS 配置失败，将使用默认值: %s", exc)
        config = build_default_config()
        save_tts_config(config)
        return config

    allowed = {f.name for f in fields(TtsConfig)}
    kwargs = {k: v for k, v in raw.items() if k in allowed}
    config = TtsConfig(**kwargs)
    apply_bundle_defaults(config)
    from pnn.tts.emotion_presets import prepare_emotion_presets

    prepare_emotion_presets(config)
    return _apply_env_overrides(config)


def save_tts_config(config: TtsConfig) -> None:
    from pnn.tts.emotion_presets import prepare_emotion_presets

    prepare_emotion_presets(config)
    TTS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    if payload.get("work_path") == "":
        payload["work_path"] = None
    if payload.get("python_path") == "":
        payload["python_path"] = None
    if _env_overrides().get("api_key"):
        payload["api_key"] = ""
    TTS_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
