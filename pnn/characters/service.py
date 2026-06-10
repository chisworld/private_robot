from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pnn.characters.pack import (
    CHARACTERS_ROOT,
    CharacterPack,
    TtsPackSettings,
    list_pack_ids,
    load_pack,
    pack_path,
    save_pack,
)
from pnn.core.paths import CONFIG_DIR, PROJECT_ROOT
from pnn.llm.config_store import load_llm_config, save_llm_config, LlmConfig

logger = logging.getLogger(__name__)

LEGACY_CONFIG_DIR = CONFIG_DIR
TTS_CONFIG_PATH = CONFIG_DIR / "tts.json"
MEMORY_CONFIG_PATH = CONFIG_DIR / "memory.json"


class CharacterPackService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_id: str | None = None
        self._applied_pack_mtime: dict[str, float] = {}

    def ensure_migrated(self) -> None:
        """将旧版 data/config/{角色}.json 迁入角色包。"""
        with self._lock:
            if list_pack_ids():
                try:
                    from pnn.tts.character_layout import (
                        LEGACY_FLAT_REF,
                        migrate_legacy_tts_assets,
                    )

                    if LEGACY_FLAT_REF.is_file():
                        migrate_legacy_tts_assets()
                except Exception as exc:
                    logger.debug("TTS 资源按角色迁移跳过: %s", exc)
                return
            CHARACTERS_ROOT.mkdir(parents=True, exist_ok=True)
            llm = load_llm_config()
            active = (llm.active_character or "树里亚").strip()
            for path in sorted(LEGACY_CONFIG_DIR.glob("*.json")):
                if path.name in ("llm.json", "tts.json", "asr.json", "pet_ui.json", "memory.json"):
                    continue
                cid = path.stem
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                pack = CharacterPack(
                    id=cid,
                    name=str(raw.get("name", cid)),
                    character_prompt=str(
                        raw.get("character_prompt") or raw.get("character_setting") or ""
                    ),
                    live2d_model_dir="live2d/14酱",
                )
                if cid == active:
                    self._apply_global_tts_to_pack(pack)
                    self._apply_global_memory_to_pack(pack)
                save_pack(pack)
                logger.info("已迁移角色包: %s", cid)
            if not list_pack_ids():
                default = CharacterPack(id="树里亚", name="我妻树里亚", live2d_model_dir="live2d/14酱")
                self._apply_global_tts_to_pack(default)
                save_pack(default)

    def _apply_global_tts_to_pack(self, pack: CharacterPack) -> None:
        if not TTS_CONFIG_PATH.is_file():
            return
        try:
            raw = json.loads(TTS_CONFIG_PATH.read_text(encoding="utf-8"))
            pack.tts = TtsPackSettings(
                ref_audio_path=str(raw.get("ref_audio_path", "")),
                prompt_text=str(raw.get("prompt_text", "")),
                prompt_lang=str(raw.get("prompt_lang", "ja")),
                text_lang=str(raw.get("text_lang", "ja")),
                gpt_model_path=str(raw.get("gpt_model_path", "")),
                sovits_model_path=str(raw.get("sovits_model_path", "")),
                speed_factor=float(raw.get("speed_factor", 1.0)),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    def _apply_global_memory_to_pack(self, pack: CharacterPack) -> None:
        if not MEMORY_CONFIG_PATH.is_file():
            return
        try:
            raw = json.loads(MEMORY_CONFIG_PATH.read_text(encoding="utf-8"))
            pack.memory_core_card = str(raw.get("core_card", ""))
        except json.JSONDecodeError:
            pass

    def list_packs(self) -> list[dict[str, str]]:
        self.ensure_migrated()
        from pnn.llm.character_store import list_characters

        return list_characters()

    def get_pack(self, char_id: str) -> CharacterPack | None:
        self.ensure_migrated()
        return load_pack(char_id)

    def get_active_id(self) -> str:
        self.ensure_migrated()
        llm = load_llm_config()
        llm_id = (llm.active_character or "").strip()
        if llm_id:
            if self._active_id != llm_id:
                self._active_id = llm_id
            return llm_id
        if self._active_id:
            return self._active_id
        pack_ids = list_pack_ids()
        return pack_ids[0] if pack_ids else "树里亚"

    def get_active_pack(self) -> CharacterPack | None:
        return self.get_pack(self.get_active_id())

    def sync_pack_tts_from_global(self, pack: CharacterPack) -> CharacterPack:
        """将当前 data/config/tts.json 写入角色包（避免角色页与 TTS 页双份维护）。"""
        if not TTS_CONFIG_PATH.is_file():
            return pack
        try:
            raw = json.loads(TTS_CONFIG_PATH.read_text(encoding="utf-8"))
            pack.tts = TtsPackSettings(
                ref_audio_path=str(raw.get("ref_audio_path", pack.tts.ref_audio_path)),
                prompt_text=str(raw.get("prompt_text", pack.tts.prompt_text)),
                prompt_lang=str(raw.get("prompt_lang", pack.tts.prompt_lang)),
                text_lang=str(raw.get("text_lang", pack.tts.text_lang)),
                gpt_model_path=str(raw.get("gpt_model_path", pack.tts.gpt_model_path)),
                sovits_model_path=str(raw.get("sovits_model_path", pack.tts.sovits_model_path)),
                speed_factor=float(raw.get("speed_factor", pack.tts.speed_factor)),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return pack

    def save_pack_data(self, pack: CharacterPack) -> CharacterPack:
        with self._lock:
            return save_pack(pack)

    def apply_active_from_llm(self, *, persist_llm: bool = False) -> CharacterPack | None:
        """按 llm.json 的 active_character 应用角色包（API/桌宠启动时调用）。"""
        self.ensure_migrated()
        llm = load_llm_config()
        cid = (llm.active_character or "").strip()
        if not cid or self.get_pack(cid) is None:
            return None
        return self.apply_pack(cid, persist_llm=persist_llm)

    def apply_pack(
        self,
        char_id: str,
        *,
        persist_llm: bool = True,
        schedule_warm: bool = True,
    ) -> CharacterPack:
        """切换当前角色：同步 LLM / TTS / 记忆核心设定。"""
        self.ensure_migrated()
        pack = load_pack(char_id)
        if pack is None:
            raise ValueError(f"角色包不存在: {char_id}")

        from pnn.characters.pack import pack_path

        llm = load_llm_config()
        llm_active = (llm.active_character or "").strip()
        path = pack_path(pack.id)
        pack_mtime = path.stat().st_mtime if path.is_file() else 0.0
        with self._lock:
            already_active = self._active_id == pack.id
            same_mtime = self._applied_pack_mtime.get(pack.id) == pack_mtime
        if already_active and llm_active == pack.id and same_mtime:
            logger.debug("角色包已是当前激活: %s", pack.id)
            return pack

        with self._lock:
            old_id = self._active_id

        if old_id and old_id != pack.id:
            try:
                from pnn.memory.service import memory_service

                memory_service.flush_session_writes(old_id)
            except Exception as exc:
                logger.warning("切换角色前写入记忆失败: %s", exc)

        with self._lock:
            self._active_id = pack.id
        if persist_llm:
            llm.active_character = pack.id
            save_llm_config(llm, keep_api_key=True)

        # 勿在 character 锁内调用 TTS 重载/预热，避免与后台 warmup 抢锁导致 HTTP 超时
        self._push_tts_from_pack(pack)
        self._push_memory_core_from_pack(pack)
        self._reload_tts_runtime(pack.id, warm_models=False)
        if schedule_warm:
            try:
                from pnn.tts.service import tts_service

                tts_service.schedule_warm_models()
            except Exception:
                pass

        legacy = LEGACY_CONFIG_DIR / f"{pack.id}.json"
        legacy.write_text(
            json.dumps(
                {"name": pack.name, "character_prompt": pack.character_prompt},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with self._lock:
            self._applied_pack_mtime[pack.id] = pack_mtime
        logger.info("已应用角色包: %s (live2d=%s)", pack.id, pack.live2d_model_dir)
        return pack

    def _push_tts_from_pack(self, pack: CharacterPack) -> None:
        if not TTS_CONFIG_PATH.is_file():
            return
        try:
            raw = json.loads(TTS_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        from pnn.tts.character_layout import read_prompt_text
        from pnn.tts.config_store import resolve_model_file_path

        t = pack.tts
        prompt = read_prompt_text(pack.id) or t.prompt_text
        ref = t.ref_audio_path
        gpt = resolve_model_file_path(t.gpt_model_path) if t.gpt_model_path else ""
        sovits = resolve_model_file_path(t.sovits_model_path) if t.sovits_model_path else ""
        if ref:
            raw["ref_audio_path"] = ref
        if prompt:
            raw["prompt_text"] = prompt
        if t.prompt_lang:
            raw["prompt_lang"] = t.prompt_lang
        if t.text_lang:
            raw["text_lang"] = t.text_lang
        if gpt:
            raw["gpt_model_path"] = gpt
        if sovits:
            raw["sovits_model_path"] = sovits
        raw["speed_factor"] = t.speed_factor
        from pnn.tts.voice_library import apply_voice_emotions_to_tts_raw, load_voice_emotions

        lib = load_voice_emotions(pack.id)
        if lib and lib.presets:
            apply_voice_emotions_to_tts_raw(
                raw,
                lib,
                pack_ref=ref,
                pack_prompt=prompt,
            )
        else:
            active_id = str(raw.get("active_emotion_id") or "default")
            presets = raw.get("emotion_presets") or []
            for item in presets:
                if not isinstance(item, dict):
                    continue
                if item.get("id") == active_id or item.get("id") == "default":
                    if ref:
                        item["ref_audio_path"] = ref
                    if prompt:
                        item["prompt_text"] = prompt
                    if t.prompt_lang:
                        item["prompt_lang"] = t.prompt_lang
            raw["emotion_presets"] = presets
        TTS_CONFIG_PATH.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            from pnn.tts.service import tts_service

            tts_service.invalidate_config_cache()
        except Exception:
            pass

    def _reload_tts_runtime(self, char_id: str, *, warm_models: bool = False) -> None:
        try:
            from pnn.tts.service import tts_service

            tts_service.reload_for_active_character(char_id, warm_models=warm_models)
        except Exception as exc:
            logger.warning("刷新 TTS 运行时配置失败: %s", exc)

    def _push_memory_core_from_pack(self, pack: CharacterPack) -> None:
        from pnn.memory.config_store import load_memory_config, save_memory_config

        cfg = load_memory_config()
        if pack.memory_core_card.strip():
            cfg.core_card = pack.memory_core_card.strip()
            save_memory_config(cfg)

    def create_pack(self, char_id: str, *, name: str = "", clone_from: str | None = None) -> CharacterPack:
        self.ensure_migrated()
        cid = char_id.strip()
        if load_pack(cid) is not None:
            raise ValueError(f"角色包已存在: {cid}")
        if clone_from:
            base = load_pack(clone_from)
            if base is None:
                raise ValueError(f"模板角色不存在: {clone_from}")
            pack = CharacterPack(
                id=cid,
                name=name or base.name,
                character_prompt=base.character_prompt,
                live2d_model_dir=base.live2d_model_dir,
                tts=TtsPackSettings(**asdict(base.tts)),
                memory_core_card="",
            )
        else:
            from pnn.tts.character_layout import default_tts_pack_settings

            pack = CharacterPack(id=cid, name=name or cid, tts=default_tts_pack_settings(cid))
        return save_pack(pack)


character_pack_service = CharacterPackService()
