"""PNN Garden API 客户端（8765）：LLM 流式、TTS、ASR、配置。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Callable

import requests

from pnn.core.env import load_env
from pnn.core.paths import api_base_url, api_ws_asr_url
from pnn.pet.console_log import log_tts
from pnn.pet.tts_local import start_local_server

logger = logging.getLogger(__name__)

load_env()
DEFAULT_API_BASE = api_base_url()
DEFAULT_WS_URL = api_ws_asr_url()


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class StreamResult:
    text: str = ""
    error: str | None = None


def _parse_http_error(resp: requests.Response) -> str:
    text = resp.text or resp.reason or "请求失败"
    try:
        data = resp.json()
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            return "; ".join(str(d.get("msg", d)) for d in detail)
    except (json.JSONDecodeError, AttributeError):
        pass
    return text


class PetApiClient:
    """桌宠与本地 API 网关通信。"""

    def __init__(self, base_url: str = DEFAULT_API_BASE, ws_url: str = DEFAULT_WS_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self._session = requests.Session()

    def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        timeout: float = 30,
    ) -> Any:
        r = self._session.request(
            method,
            f"{self.base_url}{path}",
            json=payload,
            timeout=timeout,
        )
        if not r.ok:
            raise RuntimeError(_parse_http_error(r))
        if not r.content:
            return {}
        return r.json()

    def health(self, *, timeout: float = 1.0) -> bool:
        try:
            r = self._session.get(f"{self.base_url}/api/health", timeout=timeout)
            return r.ok
        except requests.RequestException:
            return False

    def tts_health(self, *, timeout: float = 10.0) -> dict[str, Any]:
        try:
            return self._json("GET", "/api/tts/health", timeout=timeout)
        except requests.Timeout:
            return {"ok": False, "error": "API 响应超时（可能正在加载 TTS 或合成中）"}
        except requests.RequestException as exc:
            return {"ok": False, "error": str(exc)}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    def wait_tts_ready(self, timeout: float = 120.0, *, poll: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        interval = max(0.25, poll)
        while time.monotonic() < deadline:
            if self.tts_health().get("ok"):
                return True
            time.sleep(interval)
        return False

    def kick_tts_warmup(self) -> None:
        """非阻塞：请求 API 执行 TTS preload（配置已加载 + 后台起 9880）。"""
        if self.wait_tts_ready(timeout=2.0):
            return
        try:
            self._json("POST", "/api/tts/preload", payload={}, timeout=15)
        except Exception as exc:
            logger.warning("TTS preload 请求失败: %s", exc)
            try:
                self.start_tts_server()
            except Exception as exc2:
                logger.warning("TTS 回退启动失败: %s", exc2)

    def start_tts_server(self) -> dict[str, Any]:
        try:
            return self._json("POST", "/api/tts/server/start", payload={}, timeout=15)
        except RuntimeError as exc:
            msg = str(exc)
            logger.warning("API 启动 TTS 失败: %s，尝试本地拉起", msg)
            if start_local_server(wait_ready=False):
                return {"ok": False, "status": "starting", "local": True}
            return {"ok": False, "error": msg}

    def ensure_tts_ready(self, timeout: float = 120.0) -> bool:
        if self.wait_tts_ready(timeout=6.0):
            return True
        self.start_tts_server()
        if self.wait_tts_ready(timeout=timeout):
            return True
        return start_local_server(wait_ready=True, timeout=timeout)

    def get_chat_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/chat/config")

    def reload_chat_config(self) -> dict[str, Any]:
        return self._json("POST", "/api/chat/config/reload")

    def update_chat_config(self, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/chat/config", payload=fields)

    def list_characters(self) -> list[dict[str, Any]]:
        data = self._json("GET", "/api/chat/characters")
        return data.get("characters", [])

    def set_active_character(self, char_id: str) -> dict[str, Any]:
        return self.update_chat_config(active_character=char_id)

    def list_character_packs(self) -> list[dict[str, Any]]:
        data = self._json("GET", "/api/characters/packs")
        return data.get("items", [])

    def get_character_pack(self, char_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/characters/packs/{char_id}")

    def save_character_pack(self, char_id: str, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", f"/api/characters/packs/{char_id}", payload=fields)

    def apply_character_pack(self, char_id: str) -> dict[str, Any]:
        return self._json("POST", f"/api/characters/packs/{char_id}/apply")

    def get_memory_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/memory/config")

    def update_memory_config(self, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/memory/config", payload=fields)

    def list_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        data = self._json("GET", f"/api/memory/list?limit={limit}")
        return data.get("items", [])

    def delete_memory(self, memory_id: str) -> None:
        self._json("DELETE", f"/api/memory/{memory_id}")

    def get_translate_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/translate/config")

    def update_translate_config(self, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/translate/config", payload=fields)

    def translate_text(self, text: str) -> str:
        data = self._json("POST", "/api/translate", payload={"text": text})
        return str(data.get("text", text))

    def get_tts_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/tts/config")

    def update_tts_config(self, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/tts/config", payload=fields)

    def get_asr_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/config")

    def update_asr_config(self, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/config", payload=fields)

    def stream_chat(
        self,
        message: str,
        history: list[ChatMessage],
        on_delta: Callable[[str], None] | None = None,
        *,
        pet_expression_prompt: str | None = None,
        cancel: threading.Event | None = None,
    ) -> StreamResult:
        payload: dict[str, Any] = {
            "message": message,
            "history": [{"role": m.role, "content": m.content} for m in history],
        }
        if pet_expression_prompt:
            payload["pet_expression_prompt"] = pet_expression_prompt
        result = StreamResult()
        try:
            with self._session.post(
                f"{self.base_url}/api/chat/completions/stream",
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                if not resp.ok:
                    result.error = _parse_http_error(resp)
                    return result
                buf = ""
                for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                    if cancel is not None and cancel.is_set():
                        break
                    if not chunk:
                        continue
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            ev = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if ev.get("error"):
                            result.error = str(ev["error"])
                            return result
                        delta = ev.get("delta")
                        if delta:
                            result.text += delta
                            if on_delta:
                                on_delta(result.text)
                        if ev.get("done"):
                            return result
        except requests.RequestException as exc:
            result.error = str(exc)
        return result

    def synthesize_tts(
        self,
        text: str,
        *,
        log_progress: bool = False,
        cancel: threading.Event | None = None,
        on_progress: Callable[[str, int], None] | None = None,
    ) -> bytes:
        def _ui(msg: str, pct: int) -> None:
            if on_progress is not None:
                on_progress(msg, pct)

        if log_progress:
            log_tts("1/4", "检查 TTS 服务是否就绪")
        _ui("检查 TTS 服务…", 8)
        if cancel is not None and cancel.is_set():
            raise InterruptedError("TTS 已取消")
        if not self.ensure_tts_ready(timeout=120.0):
            raise RuntimeError("TTS 服务未就绪")
        preview = text.replace("\n", " ").strip()
        if len(preview) > 80:
            preview = preview[:80] + "…"
        if log_progress:
            log_tts("2/4", f"提交合成请求（{len(text)} 字）{preview}")
        _ui(f"提交合成：{preview or '…'}", 18)
        t0 = time.monotonic()
        r = self._session.post(
            f"{self.base_url}/api/tts/synthesize",
            json={"text": text},
            timeout=300,
            stream=True,
        )
        if log_progress:
            log_tts("3/4", f"等待 GPT-SoVITS 推理（HTTP {r.status_code}）")
        _ui("GPT-SoVITS 推理合成中…", 32)
        if not r.ok:
            raise RuntimeError(_parse_http_error(r))
        chunks: list[bytes] = []
        last_log = t0
        last_ui = t0
        for chunk in r.iter_content(chunk_size=65536):
            if cancel is not None and cancel.is_set():
                r.close()
                raise InterruptedError("TTS 已取消")
            if not chunk:
                continue
            chunks.append(chunk)
            now = time.monotonic()
            total = sum(len(c) for c in chunks)
            if log_progress and now - last_log >= 2.0:
                log_tts(
                    "3/4",
                    f"接收音频流… 已 {total} 字节，耗时 {now - t0:.1f}s",
                )
                last_log = now
            if on_progress is not None and now - last_ui >= 0.25:
                pct = min(92, 32 + int((now - t0) * 10) + min(30, total // 8000))
                _ui(f"接收音频 {total // 1024} KB · {now - t0:.1f}s", pct)
                last_ui = now
        data = b"".join(chunks)
        if log_progress:
            log_tts(
                "4/4",
                f"合成完成，音频 {len(data)} 字节，总耗时 {time.monotonic() - t0:.1f}s",
            )
        _ui("合成完成，准备播放", 100)
        return data

    def asr_stream_start(self) -> dict[str, Any]:
        return self._json("POST", "/api/stream/start", timeout=30)

    def asr_stream_stop(self) -> None:
        try:
            self._session.post(f"{self.base_url}/api/stream/stop", timeout=10)
        except requests.RequestException:
            pass
