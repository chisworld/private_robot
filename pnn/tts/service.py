from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pnn.core.paths import PROJECT_ROOT
from pnn.tts.config_store import apply_bundle_defaults, load_tts_config, save_tts_config
from pnn.tts.emotion_presets import apply_preset_to_config, find_preset, prepare_emotion_presets
from pnn.tts.manager import TTSAdapterFactory, TTSManager
from pnn.tts.paths import TTS_CONFIG_PATH

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "tts" / "output"

SUPPORTED_PROVIDERS: list[dict[str, str]] = [
    {"id": "gpt-sovits", "label": "GPT-SoVITS"},
    {"id": "genie-tts", "label": "Genie TTS"},
    {"id": "index-tts", "label": "Index TTS"},
    {"id": "cosyvoice", "label": "CosyVoice (阿里云)"},
]

SUPPORTED_TEXT_LANGS: list[dict[str, str]] = [
    {"code": "zh", "label": "中文"},
    {"code": "ja", "label": "日本語"},
    {"code": "en", "label": "English"},
    {"code": "ko", "label": "한국어"},
    {"code": "yue", "label": "粤语"},
]


@dataclass
class TtsConfig:
    provider: str = "gpt-sovits"
    server_url: str = "http://127.0.0.1:9880"
    work_path: str | None = None
    python_path: str | None = None
    api_key: str = ""
    gpt_model_path: str = ""
    sovits_model_path: str = ""
    ref_audio_path: str = ""
    prompt_text: str = ""
    prompt_lang: str = "zh"
    text_lang: str = "zh"
    speed_factor: float = 1.0
    auto_start_server: bool = True
    character_name: str = ""
    onnx_model_dir: str = ""
    emotion_presets: list[dict[str, Any]] = field(default_factory=list)
    active_emotion_id: str = ""


class TtsService:
    """TTS 服务：使用与 AI_assistant 相同的 Adapter + Manager 架构。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config_mtime: float = 0.0
        self._config = self._load_config_fresh()
        self._manager: TTSManager | None = None
        self._last_error: str | None = None
        self._boot_running = False
        # (provider, gpt_path, sovits_path) — 避免每次合成重复 switch_model
        self._models_applied_key: tuple[str, str, str] = ("", "", "")

    def _config_file_mtime(self) -> float:
        try:
            return TTS_CONFIG_PATH.stat().st_mtime if TTS_CONFIG_PATH.is_file() else 0.0
        except OSError:
            return 0.0

    def _merge_active_pack_tts(self, cfg: TtsConfig) -> None:
        """将当前角色包 TTS 字段合并进内存配置（不重复写 tts.json）。"""
        try:
            from pnn.characters.service import character_pack_service

            character_pack_service.ensure_migrated()
            pack = character_pack_service.get_active_pack()
            if pack is None:
                return
            t = pack.tts
            if t.ref_audio_path and Path(t.ref_audio_path).is_file():
                from pnn.tts.config_store import mirror_reference_audio

                cfg.ref_audio_path = mirror_reference_audio(t.ref_audio_path)
            if t.prompt_text:
                cfg.prompt_text = t.prompt_text
            if t.prompt_lang:
                cfg.prompt_lang = t.prompt_lang
            if t.text_lang:
                cfg.text_lang = t.text_lang
            from pnn.tts.config_store import resolve_model_file_path

            if t.gpt_model_path:
                resolved = resolve_model_file_path(t.gpt_model_path)
                if Path(resolved).is_file():
                    cfg.gpt_model_path = resolved
            if t.sovits_model_path:
                resolved = resolve_model_file_path(t.sovits_model_path)
                if Path(resolved).is_file():
                    cfg.sovits_model_path = resolved
            if t.speed_factor:
                cfg.speed_factor = float(t.speed_factor)
        except Exception as exc:
            logger.debug("合并角色包 TTS 失败（可忽略）: %s", exc)

    def _load_config_fresh(self) -> TtsConfig:
        cfg = load_tts_config()
        self._merge_active_pack_tts(cfg)
        self._config_mtime = self._config_file_mtime()
        return cfg

    def _reload_config_if_needed(self) -> None:
        mtime = self._config_file_mtime()
        if mtime == self._config_mtime:
            return
        with self._lock:
            if mtime != self._config_mtime:
                self._config = self._load_config_fresh()
                self._models_applied_key = ("", "", "")

    def _local_asset_warnings(self) -> list[str]:
        warnings: list[str] = []
        cfg = self._config
        bundle = Path(cfg.work_path) if cfg.work_path else None
        if bundle is None or not bundle.is_dir():
            warnings.append(
                "GPT-SoVITS 整合包未找到：请解压到 models/TTS/GPT-SoVITS-v2pro-20250604（含 api_v2.py）"
            )
        elif not (bundle / "runtime" / "python.exe").is_file():
            warnings.append(f"整合包缺少 runtime/python.exe: {bundle}")
        if cfg.gpt_model_path and not Path(cfg.gpt_model_path).is_file():
            warnings.append(f"GPT 权重不存在: {cfg.gpt_model_path}")
        if cfg.sovits_model_path and not Path(cfg.sovits_model_path).is_file():
            warnings.append(f"SoVITS 权重不存在: {cfg.sovits_model_path}")
        if cfg.ref_audio_path and not Path(cfg.ref_audio_path).is_file():
            warnings.append(f"参考音频不存在: {cfg.ref_audio_path}")
        return warnings

    def bootstrap(self) -> dict[str, Any]:
        """进程启动时同步加载配置与本地路径校验（不启动 9880）。"""
        with self._lock:
            self._config = self._load_config_fresh()
            warnings = self._local_asset_warnings()
        if warnings:
            for msg in warnings:
                logger.warning("TTS 本地资源: %s", msg)
        else:
            logger.info(
                "TTS 配置已加载 provider=%s work_path=%s",
                self._config.provider,
                self._config.work_path or "(未设置)",
            )
        return {
            "ok": not any("整合包未找到" in w for w in warnings),
            "warnings": warnings,
            "provider": self._config.provider,
        }

    def preload(self, *, wait_ready: bool = False) -> dict[str, Any]:
        """启动预热：加载配置 → 后台拉起 GPT-SoVITS → 就绪后切换模型。"""
        boot = self.bootstrap()
        cfg = self._config
        if cfg.provider.lower() == "cosyvoice":
            return boot | {"status": "cloud", "server_alive": True}
        if not cfg.work_path:
            return boot | {"status": "skipped", "reason": "no work_path"}
        if not cfg.auto_start_server:
            return boot | {"status": "skipped", "reason": "auto_start_server=false"}

        if wait_ready:
            try:
                result = self.start_server(force_restart=False)
                return boot | result | {"models_warmed": True}
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                return boot | {"ok": False, "status": "error", "error": str(exc)}

        result = self.begin_start_server(force_restart=False)
        return boot | result

    def _warm_models(self) -> None:
        if not self.check_server(probe=True).get("ok"):
            return
        manager = self._get_manager()
        self._apply_models_if_needed(manager)

    def _model_apply_key(self) -> tuple[str, str, str]:
        from pnn.tts.adapters import _norm_weight_path

        return (
            self._config.provider.lower(),
            _norm_weight_path(self._config.gpt_model_path),
            _norm_weight_path(self._config.sovits_model_path),
        )

    def _apply_models_if_needed(self, manager: TTSManager) -> None:
        with self._lock:
            key = self._model_apply_key()
            if key == self._models_applied_key:
                return
            self._apply_models(manager)
            self._models_applied_key = key

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            self._reload_config_if_needed()
            health = self.check_server(probe=True)
            return asdict(self._config) | {
                "server_alive": health.get("ok", False),
                "last_error": self._last_error or health.get("error"),
                "service_version": 4,
                "asset_warnings": self._local_asset_warnings(),
            }

    def update_config(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            old_provider = self._config.provider
            old_url = self._config.server_url
            old_work = self._config.work_path
            for key, value in kwargs.items():
                if not hasattr(self._config, key):
                    continue
                setattr(self._config, key, value)
            apply_bundle_defaults(self._config)
            prepare_emotion_presets(self._config)
            # 仅切换引擎/地址/整合包时重启 TTS 进程；普通保存配置不要杀掉 9880
            adapter_changed = (
                self._config.provider != old_provider
                or self._config.server_url != old_url
                or self._config.work_path != old_work
            )
            self._reset_manager(stop_server=adapter_changed)
            self._last_error = None
            self._models_applied_key = ("", "", "")
            save_tts_config(self._config)
            self._config_mtime = self._config_file_mtime()
            return self.get_config()

    def _reset_manager(self, *, stop_server: bool = True) -> None:
        if self._manager is not None:
            if stop_server:
                self._manager.shutdown()
            self._manager = None

    def _adapter_kwargs(self) -> dict[str, Any]:
        cfg = self._config
        provider = cfg.provider.lower()

        if provider == "gpt-sovits":
            return {
                "tts_server_url": cfg.server_url,
                "gpt_sovits_work_path": cfg.work_path,
                "python_executable": cfg.python_path,
                "auto_start": False,
            }
        if provider == "genie-tts":
            return {
                "tts_server_url": cfg.server_url,
                "tts_work_path": cfg.work_path,
                "gpt_sovits_work_path": cfg.work_path,
                "auto_start": False,
            }
        if provider == "index-tts":
            return {
                "index_server_url": cfg.server_url,
                "index_server_work_path": cfg.work_path,
                "auto_start": False,
            }
        if provider == "cosyvoice":
            return {"api_key": cfg.api_key}
        raise ValueError(f"Unsupported TTS provider: {cfg.provider}")

    def _get_manager(self) -> TTSManager:
        with self._lock:
            if self._manager is None:
                adapter = TTSAdapterFactory.create_adapter(
                    self._config.provider,
                    **self._adapter_kwargs(),
                )
                manager = TTSManager(tts_server_url=self._config.server_url)
                manager.set_tts_adapter(adapter)
                manager.set_language(self._config.text_lang)
                self._manager = manager
            return self._manager

    def _apply_models(self, manager: TTSManager) -> None:
        cfg = self._config
        provider = cfg.provider.lower()
        if provider == "gpt-sovits":
            manager.switch_model(
                {
                    "gpt_model_path": cfg.gpt_model_path,
                    "sovits_model_path": cfg.sovits_model_path,
                }
            )
        elif provider == "genie-tts":
            manager.switch_model(
                {
                    "character_name": cfg.character_name,
                    "gpt_model_path": cfg.gpt_model_path,
                    "sovits_model_path": cfg.sovits_model_path,
                    "onnx_model_dir": cfg.onnx_model_dir or None,
                }
            )
        elif provider == "index-tts":
            manager.switch_model({"model_id": cfg.gpt_model_path or None})

    def _ensure_server_ready(self) -> None:
        if self.check_server(probe=True).get("ok"):
            return
        if not self._config.work_path:
            raise RuntimeError("未配置 GPT-SoVITS 整合包路径（work_path）")
        if self._config.provider.lower() == "cosyvoice":
            return
        with self._lock:
            boot_running = self._boot_running
        if boot_running:
            # 后台已在启动，避免在 API 请求里长时间占满 worker
            try:
                self._wait_server_ready(timeout=45.0)
            except TimeoutError:
                raise RuntimeError(
                    "GPT-SoVITS 仍在启动中，请稍候再试（首次加载模型约 2～8 分钟）"
                ) from None
            return
        logger.info("GPT-SoVITS 未运行，合成前自动启动…")
        self.start_server(force_restart=False)

    def synthesize(
        self,
        text: str,
        *,
        output_path: str | Path | None = None,
        emotion_id: str | None = None,
    ) -> Path:
        if not text.strip():
            raise ValueError("合成文本不能为空")

        try:
            with self._lock:
                self._reload_config_if_needed()
                if emotion_id:
                    prepare_emotion_presets(self._config)
                    preset = find_preset(self._config, emotion_id)
                    if preset:
                        if not (preset.get("ref_audio_path") or "").strip():
                            raise ValueError(
                                f"情绪「{preset.get('label') or emotion_id}」未配置参考音频，"
                                "请在 TTS 页补全或改用「默认」"
                            )
                        apply_preset_to_config(self._config, preset)
                    else:
                        raise ValueError(f"未找到情绪预设: {emotion_id}")
            self._ensure_server_ready()
            with self._lock:
                manager = self._get_manager()
                manager.set_language(self._config.text_lang)
            self._apply_models_if_needed(manager)
            preview = text.strip().replace("\n", " ")[:64]
            if len(text.strip()) > 64:
                preview += "…"
            logger.info(
                "TTS 推理中 provider=%s 字数=%d 文本=%s",
                self._config.provider,
                len(text.strip()),
                preview,
            )
            result = manager.generate_tts(
                text.strip(),
                ref_audio_path=self._config.ref_audio_path,
                prompt_text=self._config.prompt_text,
                prompt_lang=self._config.prompt_lang,
                character_name=self._config.character_name or None,
                speed_factor=self._config.speed_factor,
            )
            if not result:
                health = self.check_server(probe=True)
                if not health.get("ok"):
                    raise RuntimeError(
                        "GPT-SoVITS 未运行或仍在加载模型，请稍候再试，或点击「保存并启动服务」"
                    )
                detail = getattr(manager.tts_adapter, "_last_error", None)
                if detail:
                    raise RuntimeError(f"TTS 合成失败: {detail}")
                raise RuntimeError("TTS 合成失败，请检查参考音频与模型配置")

            src = Path(result)
            if output_path is None:
                DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                output_path = DEFAULT_OUTPUT_DIR / f"tts_{abs(hash(text)) & 0xFFFFFFFF:08x}.wav"
            dest = Path(output_path).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != dest:
                shutil.copy2(src, dest)
            with self._lock:
                self._last_error = None
            logger.info("TTS 推理完成 → %s", dest)
            return dest
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.exception("TTS synthesize failed")
            raise

    def synthesize_bytes(self, text: str) -> bytes:
        path = self.synthesize(text)
        return path.read_bytes()

    def check_server(self, *, probe: bool = True) -> dict[str, Any]:
        try:
            if self._manager is not None:
                alive = self._manager.is_server_alive()
            elif probe and self._config.provider != "cosyvoice":
                from pnn.tts.probe import probe_http_server_cached

                alive = probe_http_server_cached(self._config.server_url)
            else:
                alive = False
            return {"ok": alive, "server_url": self._config.server_url}
        except Exception as exc:
            return {"ok": False, "server_url": self._config.server_url, "error": str(exc)}

    def _boot_timeout_seconds(self) -> float:
        raw = os.getenv("TTS_BOOT_TIMEOUT", "120").strip()
        try:
            return max(30.0, float(raw))
        except ValueError:
            return 120.0

    def _server_process_exited(self, manager: TTSManager) -> int | None:
        adapter = getattr(manager, "tts_adapter", None)
        proc = getattr(adapter, "_server_process", None) if adapter else None
        if proc is None:
            return None
        return proc.poll()

    def _wait_server_ready(self, timeout: float | None = None) -> dict[str, Any]:
        """等待 GPT-SoVITS HTTP 端口可访问（模型在首次 /tts 或 set_weights 时再加载）。"""
        wait = self._boot_timeout_seconds() if timeout is None else timeout
        manager = self._get_manager()
        deadline = time.monotonic() + wait
        started = time.monotonic()
        last_log = started
        while time.monotonic() < deadline:
            exit_code = self._server_process_exited(manager)
            if exit_code is not None:
                log_hint = ""
                work = self._config.work_path or ""
                if work:
                    log_hint = f" 请查看 {work}/gpt_sovits_boot.log"
                raise RuntimeError(
                    f"GPT-SoVITS 进程已退出 (code={exit_code})，"
                    f"端口 {self._config.server_url} 未启动。{log_hint}"
                )
            if manager.is_server_alive():
                from pnn.tts.probe import invalidate_probe_cache

                invalidate_probe_cache(self._config.server_url)
                with self._lock:
                    self._last_error = None
                elapsed = time.monotonic() - started
                logger.info("GPT-SoVITS HTTP 已就绪（%.0fs）", elapsed)
                return self.check_server() | {"status": "ready", "elapsed_s": elapsed}
            now = time.monotonic()
            if now - last_log >= 15.0:
                logger.info(
                    "等待 GPT-SoVITS HTTP… 已 %.0fs / %.0fs",
                    now - started,
                    wait,
                )
                last_log = now
            time.sleep(1.0)
        raise TimeoutError(
            f"TTS 服务在 {wait:.0f}s 内未响应（请确认 9880 未被占用，"
            "或查看整合包目录下 gpt_sovits_boot.log）"
        )

    def start_server(self, *, force_restart: bool = True) -> dict[str, Any]:
        if not self._config.work_path:
            raise RuntimeError("未配置 GPT-SoVITS 整合包路径（work_path）")

        manager = self._get_manager()
        manager.start_server(force_restart=force_restart)
        result = self._wait_server_ready()
        self._warm_models()
        return result

    def begin_start_server(self, *, force_restart: bool = True) -> dict[str, Any]:
        """非阻塞启动：先同步拉起进程，再后台等待模型加载完成。"""
        if not force_restart:
            health = self.check_server(probe=True)
            if health.get("ok"):
                return health | {"status": "ready"}

        if not self._config.work_path:
            raise RuntimeError("未配置 GPT-SoVITS 整合包路径（work_path）")

        with self._lock:
            if self._boot_running:
                return {
                    "ok": False,
                    "status": "starting",
                    "server_url": self._config.server_url,
                }
            self._boot_running = True
            self._last_error = None

        manager = self._get_manager()
        manager.start_server(force_restart=force_restart)

        def _worker() -> None:
            try:
                self._wait_server_ready()
                logger.info("GPT-SoVITS HTTP 已就绪，正在加载/切换角色权重（首次可能 3～8 分钟）…")
                try:
                    self._warm_models()
                    logger.info("TTS 后台启动完成，模型已切换")
                except Exception as warm_exc:
                    logger.warning(
                        "TTS 权重预热未完成（首次语音时会继续加载）: %s",
                        warm_exc,
                    )
            except Exception as exc:
                logger.exception("TTS background boot failed")
                with self._lock:
                    self._last_error = str(exc)
            finally:
                with self._lock:
                    self._boot_running = False

        threading.Thread(target=_worker, name="tts-boot", daemon=True).start()
        return {
            "ok": False,
            "status": "starting",
            "server_url": self._config.server_url,
        }

    def stop_server(self) -> None:
        from pnn.tts.probe import invalidate_probe_cache

        with self._lock:
            url = self._config.server_url
            self._reset_manager(stop_server=True)
        invalidate_probe_cache(url)


tts_service = TtsService()
