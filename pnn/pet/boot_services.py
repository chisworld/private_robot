"""桌宠分阶段启动：Live2D 与问候语音优先，API/TTS 等在后台拉起。"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("pet")


def kick_tts_warmup() -> None:
    try:
        from pnn.pet.api_client import PetApiClient

        PetApiClient().kick_tts_warmup()
        logger.info("已请求后台 TTS 预热（9880 + 权重，首次约 1～8 分钟）")
    except Exception as exc:
        logger.debug("TTS 预热请求跳过: %s", exc)


def ensure_api_and_kick_tts(*, timeout: float = 90.0) -> bool:
    from pnn.core.api_health import ensure_api_for_pet, is_api_ready_for_pet

    if is_api_ready_for_pet(timeout=0.8):
        logger.info("API 8765 已就绪")
        kick_tts_warmup()
        return True
    logger.info("后台启动 API 8765（人物模型就绪后）…")
    if ensure_api_for_pet(timeout=timeout):
        logger.info("API 8765 已就绪")
        kick_tts_warmup()
        return True
    logger.warning(
        "API 8765 未在 %.0fs 内就绪；日志: data\\logs\\api_boot.log",
        timeout,
    )
    return False


def ensure_api_and_kick_tts_async(*, timeout: float = 90.0) -> None:
    threading.Thread(
        target=ensure_api_and_kick_tts,
        kwargs={"timeout": timeout},
        name="pet-api-voice-boot",
        daemon=True,
    ).start()


def prune_audio_cache_async() -> None:
    def _run() -> None:
        try:
            from pnn.core.audio_cache import prune_audio_cache

            prune_audio_cache()
        except Exception as exc:
            logger.debug("音频缓存清理跳过: %s", exc)

    threading.Thread(target=_run, name="pet-audio-cache-prune", daemon=True).start()
