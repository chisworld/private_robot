"""多情绪参考音预设：加载、迁移、应用。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pnn.tts.ref_audio import mirror_emotion_reference, mirror_reference_audio

if TYPE_CHECKING:
    from pnn.tts.service import TtsConfig

PresetDict = dict[str, Any]


def _slugify(label: str, fallback: str = "emotion") -> str:
    slug = re.sub(r"[^\w\-]+", "_", label.strip(), flags=re.UNICODE).strip("_").lower()
    return slug or fallback


def _unique_id(label: str, existing: set[str]) -> str:
    base = _slugify(label)
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def normalize_presets(raw: list[Any] | None) -> list[PresetDict]:
    if not raw:
        return []

    seen: set[str] = set()
    normalized: list[PresetDict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip() or "未命名"
        preset_id = str(item.get("id") or "").strip() or _unique_id(label, seen)
        if preset_id in seen:
            preset_id = _unique_id(label, seen)
        seen.add(preset_id)
        normalized.append(
            {
                "id": preset_id,
                "label": label,
                "ref_audio_path": str(item.get("ref_audio_path") or "").strip(),
                "prompt_text": str(item.get("prompt_text") or "").strip(),
                "prompt_lang": str(item.get("prompt_lang") or "").strip(),
            }
        )
    return normalized


def migrate_legacy_preset(config: TtsConfig) -> None:
    """将旧版单一 ref_audio_path 迁移为一条默认预设。"""
    if config.emotion_presets:
        return
    ref = str(config.ref_audio_path or "").strip()
    prompt = str(config.prompt_text or "").strip()
    if not ref and not prompt:
        return
    preset_id = "default"
    config.emotion_presets = [
        {
            "id": preset_id,
            "label": "默认",
            "ref_audio_path": ref,
            "prompt_text": prompt,
            "prompt_lang": str(config.prompt_lang or "").strip(),
        }
    ]
    config.active_emotion_id = preset_id


def find_preset(config: TtsConfig, preset_id: str | None) -> PresetDict | None:
    if not preset_id:
        return None
    for item in config.emotion_presets:
        if item.get("id") == preset_id:
            return item
    return None


def find_active_preset(config: TtsConfig) -> PresetDict | None:
    preset = find_preset(config, config.active_emotion_id)
    if preset:
        return preset
    if config.emotion_presets:
        return config.emotion_presets[0]
    return None


def sync_active_from_ref_fields(config: TtsConfig) -> None:
    """保存前：把当前 ref/prompt 字段写回 active 预设。"""
    migrate_legacy_preset(config)
    if not config.emotion_presets:
        return
    active_id = config.active_emotion_id or config.emotion_presets[0]["id"]
    for item in config.emotion_presets:
        if item.get("id") == active_id:
            item["ref_audio_path"] = str(config.ref_audio_path or "").strip()
            item["prompt_text"] = str(config.prompt_text or "").strip()
            item["prompt_lang"] = str(config.prompt_lang or "").strip()
            config.active_emotion_id = active_id
            return
    config.emotion_presets[0]["ref_audio_path"] = str(config.ref_audio_path or "").strip()
    config.emotion_presets[0]["prompt_text"] = str(config.prompt_text or "").strip()
    config.emotion_presets[0]["prompt_lang"] = str(config.prompt_lang or "").strip()
    config.active_emotion_id = config.emotion_presets[0]["id"]


def apply_preset_to_config(config: TtsConfig, preset: PresetDict) -> None:
    ref = str(preset.get("ref_audio_path") or "").strip()
    if ref and Path(ref).is_file():
        ref = mirror_emotion_reference(str(preset["id"]), ref)
        preset["ref_audio_path"] = ref
    config.ref_audio_path = ref
    config.prompt_text = str(preset.get("prompt_text") or "").strip()
    prompt_lang = str(preset.get("prompt_lang") or "").strip()
    if prompt_lang:
        config.prompt_lang = prompt_lang
    config.active_emotion_id = str(preset.get("id") or "")


def prepare_emotion_presets(config: TtsConfig) -> None:
    """加载/保存前规范化预设并应用到 ref 字段。"""
    config.emotion_presets = normalize_presets(config.emotion_presets)
    migrate_legacy_preset(config)
    config.emotion_presets = normalize_presets(config.emotion_presets)

    for item in config.emotion_presets:
        ref = str(item.get("ref_audio_path") or "").strip()
        if ref and Path(ref).is_file():
            item["ref_audio_path"] = mirror_emotion_reference(str(item["id"]), ref)

    preset = find_active_preset(config)
    if preset:
        apply_preset_to_config(config, preset)
    elif config.ref_audio_path and Path(config.ref_audio_path).is_file():
        config.ref_audio_path = mirror_reference_audio(config.ref_audio_path)


def new_preset(label: str, existing_ids: set[str]) -> PresetDict:
    preset_id = _unique_id(label, existing_ids)
    return {
        "id": preset_id,
        "label": label.strip() or "未命名",
        "ref_audio_path": "",
        "prompt_text": "",
        "prompt_lang": "",
    }


def new_preset_id() -> str:
    return uuid.uuid4().hex[:8]
