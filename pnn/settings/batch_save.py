"""设置页一次性保存（单线程、单次 HTTP，避免 8+ 轮串行请求）。"""

from __future__ import annotations

import logging
from typing import Any

from pnn.asr.service import asr_service
from pnn.characters.pack import CharacterPack, TtsPackSettings
from pnn.characters.service import character_pack_service
from pnn.llm.service import llm_service
from pnn.memory.service import memory_service
from pnn.mcp.service import mcp_service
from pnn.translate.service import translate_service
from pnn.tts.service import tts_service

logger = logging.getLogger(__name__)


def _pack_tts_signature(pack: CharacterPack) -> tuple[str, ...]:
    t = pack.tts
    return (
        str(t.gpt_model_path or "").strip(),
        str(t.sovits_model_path or "").strip(),
        str(t.ref_audio_path or "").strip(),
        str(t.text_lang or "").strip(),
        str(t.prompt_text or "").strip(),
    )


def _build_pack_from_body(char_id: str, body: dict[str, Any]) -> CharacterPack:
    existing = character_pack_service.get_pack(char_id)
    if existing is None:
        raise ValueError(f"角色包不存在: {char_id}")
    pack = CharacterPack(
        id=char_id,
        name=str(body.get("name") or existing.name),
        character_prompt=str(body.get("character_prompt") or ""),
        live2d_model_dir=str(body.get("live2d_model_dir") or existing.live2d_model_dir),
        live2d_variants=list(existing.live2d_variants),
        tts=existing.tts,
        memory_core_card=str(body.get("memory_core_card") or ""),
        test_mode=bool(body.get("test_mode", existing.test_mode)),
        reply_language=str(body.get("reply_language") or existing.reply_language),
        time_greetings=existing.time_greetings,
    )
    tg_raw = body.get("time_greetings")
    if isinstance(tg_raw, dict):
        from pnn.characters.pack import TimeGreetingSettings

        merged = existing.time_greetings.to_dict()
        merged.update({k: v for k, v in tg_raw.items() if v is not None})
        pack.time_greetings = TimeGreetingSettings.from_dict(merged)
    tts_raw = body.get("tts")
    if isinstance(tts_raw, dict):
        pack.tts = TtsPackSettings.from_dict(tts_raw)
    return pack


def apply_settings_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """在 API 线程池中一次性应用设置页快照。"""
    result: dict[str, Any] = {"ok": True}
    char_id = str(payload.get("char_id") or "").strip()
    pack_body = payload.get("pack")

    if payload.get("mcp") and not payload.get("mcp_skip"):
        mcp_fields = dict(payload["mcp"])
        mcp_service.update_config(**mcp_fields)
        result["mcp_synced"] = True
    else:
        result["mcp_synced"] = False

    tts_warm = True
    if isinstance(pack_body, dict) and char_id:
        before = character_pack_service.get_pack(char_id)
        if before is not None:
            tts_warm = _pack_tts_signature(before) != _pack_tts_signature(
                _build_pack_from_body(char_id, pack_body)
            )
        pack = _build_pack_from_body(char_id, pack_body)
        saved = character_pack_service.save_pack_data(pack)
        result["pack"] = saved.to_dict()

    llm = payload.get("llm")
    if isinstance(llm, dict) and llm:
        result["llm"] = llm_service.update_config(**llm)

    if char_id:
        applied = character_pack_service.apply_pack(
            char_id,
            persist_llm=False,
            schedule_warm=tts_warm,
        )
        result["active_character"] = applied.id

    tts = payload.get("tts")
    if isinstance(tts, dict) and tts and not (isinstance(pack_body, dict) and char_id):
        result["tts"] = tts_service.update_config(**tts)

    asr = payload.get("asr")
    if isinstance(asr, dict) and asr:
        available = asr_service.list_models()["models"]
        model = asr.get("model")
        if model is not None and model not in available:
            raise ValueError(f"不支持的 ASR 模型: {model}")
        result["asr"] = asr_service.update_config(**asr)

    memory = payload.get("memory")
    if isinstance(memory, dict) and memory:
        result["memory"] = memory_service.update_config(**memory)

    translate = payload.get("translate")
    if isinstance(translate, dict) and translate:
        allowed = {"enabled", "provider", "app_id", "secret", "from_lang", "to_lang"}
        tr_payload = {k: v for k, v in translate.items() if k in allowed}
        if tr_payload:
            result["translate"] = translate_service.update_config(**tr_payload)

    launch_apps = payload.get("launch_apps")
    if isinstance(launch_apps, dict) and launch_apps:
        from pnn.launch_apps.service import launch_apps_service

        apps_raw = launch_apps.get("apps")
        folders_raw = launch_apps.get("folders")
        urls_raw = launch_apps.get("urls")
        apps_list = apps_raw if isinstance(apps_raw, list) else None
        folders_list = folders_raw if isinstance(folders_raw, list) else None
        urls_list = urls_raw if isinstance(urls_raw, list) else None
        launch_apps_service.update_config(
            enabled=launch_apps.get("enabled"),
            use_in_chat=launch_apps.get("use_in_chat"),
            apps=apps_list,
            folders=folders_list,
            urls=urls_list,
        )
        result["launch_apps"] = launch_apps_service.get_config()

    logger.info(
        "设置批量保存完成 char=%s mcp=%s tts_warm=%s",
        char_id or "-",
        result.get("mcp_synced"),
        tts_warm,
    )
    return result
