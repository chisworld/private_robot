"""PNN Garden API 客户端（8765）：LLM 流式、TTS、ASR、配置。"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pnn.core.env import load_env
from pnn.core.paths import api_base_url, api_ws_asr_url
from pnn.pet.console_log import (
    TtsTerminalBar,
    log_tts,
    pet_console_verbose,
    tts_terminal_bar_enabled,
)

logger = logging.getLogger(__name__)

# 设置页批量保存：MCP 断开、写 pack 等可能略慢于普通 API 调用
SETTINGS_SAVE_TIMEOUT = 90.0

_requests = None


def _req():
    global _requests
    if _requests is None:
        import requests as _requests_mod

        _requests = _requests_mod
    return _requests


def _resolve_api_urls(
    base_url: str | None,
    ws_url: str | None,
) -> tuple[str, str]:
    if base_url is None or ws_url is None:
        load_env()
    if base_url is None:
        base_url = api_base_url()
    if ws_url is None:
        ws_url = api_ws_asr_url()
    return base_url.rstrip("/"), ws_url


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class StreamResult:
    text: str = ""
    error: str | None = None


def _parse_http_error(resp) -> str:
    text = (resp.text or "").strip() or resp.reason or "请求失败"
    try:
        data = resp.json()
        detail = data.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, list):
            return "; ".join(str(d.get("msg", d)) for d in detail)
    except (json.JSONDecodeError, AttributeError):
        pass
    code = getattr(resp, "status_code", None)
    if code and text in ("Internal Server Error", "Service Unavailable"):
        return f"HTTP {code}（API 可能正在重启，请稍后在 MCP 页点「重启 API」）"
    return text


class PetApiClient:
    """桌宠与本地 API 网关通信。"""

    def __init__(self, base_url: str | None = None, ws_url: str | None = None) -> None:
        self.base_url, self.ws_url = _resolve_api_urls(base_url, ws_url)
        self._session = None

    def _http(self):
        if self._session is None:
            self._session = _req().Session()
        return self._session

    def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        timeout: float = 30,
    ) -> Any:
        r = self._http().request(
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
            r = self._http().get(f"{self.base_url}/api/health", timeout=timeout)
            return r.ok
        except _req().RequestException:
            return False

    def tts_health(self, *, timeout: float = 10.0) -> dict[str, Any]:
        try:
            return self._json("GET", "/api/tts/health", timeout=timeout)
        except _req().Timeout:
            return {"ok": False, "error": "API 响应超时（可能正在加载 TTS 或合成中）"}
        except _req().RequestException as exc:
            return {"ok": False, "error": str(exc)}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    def wait_tts_ready(self, timeout: float = 480.0, *, poll: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        interval = max(0.25, poll)
        while time.monotonic() < deadline:
            h = self.tts_health(timeout=min(5.0, interval + 2.0))
            if h.get("ok"):
                return True
            time.sleep(interval)
        return False

    def tts_server_online(self, *, timeout: float = 3.0) -> bool:
        """GPT-SoVITS HTTP 已监听（不要求 inference_ready）。"""
        return bool(self.tts_health(timeout=timeout).get("server_alive"))

    def kick_tts_warmup(self) -> None:
        """非阻塞：请求 API 执行 TTS preload（配置已加载 + 后台起 9880）。"""
        if self.wait_tts_ready(timeout=2.0):
            return
        try:
            self._json("POST", "/api/tts/preload", payload={}, timeout=15)
        except Exception as exc:
            msg = str(exc)
            if "shutdown" in msg.lower():
                logger.warning(
                    "API 正在关闭或已异常，跳过 TTS preload（将尝试本地 GPT-SoVITS）"
                )
            else:
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
            if "shutdown" in msg.lower():
                logger.warning("API 不可用（可能正在关闭），尝试本地拉起 GPT-SoVITS")
            else:
                logger.warning("API 启动 TTS 失败: %s，尝试本地拉起", msg)
            from pnn.pet.tts_local import start_local_server

            if start_local_server(wait_ready=False):
                return {"ok": False, "status": "starting", "local": True}
            return {"ok": False, "error": msg}

    def ensure_tts_ready(self, timeout: float = 480.0) -> bool:
        if self.wait_tts_ready(timeout=8.0):
            return True
        self.kick_tts_warmup()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            h = self.tts_health(timeout=5.0)
            if h.get("ok"):
                return True
            if h.get("server_alive") and not h.get("warming"):
                logger.info(
                    "TTS HTTP 已在线，将尝试合成（推理预热=%s）",
                    h.get("inference_ready"),
                )
                return True
            time.sleep(2.0)
        if not self.tts_server_online():
            self.start_tts_server()
            if self.wait_tts_ready(timeout=min(120.0, timeout)):
                return True
            from pnn.pet.tts_local import start_local_server

            return start_local_server(wait_ready=True, timeout=timeout)
        return self.tts_server_online()

    def get_chat_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/chat/config")

    def reload_chat_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("POST", "/api/chat/config/reload", timeout=timeout)

    def update_chat_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/chat/config", payload=fields, timeout=timeout)

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

    def save_character_pack(
        self, char_id: str, *, timeout: float = 30, **fields: Any
    ) -> dict[str, Any]:
        return self._json(
            "PUT", f"/api/characters/packs/{char_id}", payload=fields, timeout=timeout
        )

    def apply_character_pack(self, char_id: str, *, timeout: float = 30) -> dict[str, Any]:
        return self._json(
            "POST", f"/api/characters/packs/{char_id}/apply", timeout=timeout
        )

    def get_memory_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/memory/config")

    def update_memory_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/memory/config", payload=fields, timeout=timeout)

    def list_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        data = self._json("GET", f"/api/memory/list?limit={limit}")
        return data.get("items", [])

    def delete_memory(self, memory_id: str) -> None:
        self._json("DELETE", f"/api/memory/{memory_id}")

    def get_translate_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/translate/config")

    def update_translate_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/translate/config", payload=fields, timeout=timeout)

    def translate_text(self, text: str) -> str:
        data = self._json("POST", "/api/translate", payload={"text": text})
        return str(data.get("text", text))

    def get_tts_config(self, *, fresh: bool = False, probe: bool = True) -> dict[str, Any]:
        parts: list[str] = []
        if fresh:
            parts.append("fresh=1")
        if not probe:
            parts.append("probe=0")
        query = f"?{'&'.join(parts)}" if parts else ""
        return self._json("GET", f"/api/tts/config{query}")

    def update_tts_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/tts/config", payload=fields, timeout=timeout)

    def get_asr_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/config")

    def update_asr_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/config", payload=fields, timeout=timeout)

    def get_mcp_config(self) -> dict[str, Any]:
        return self._json("GET", "/api/mcp/config")

    def get_mcp_status(self) -> dict[str, Any]:
        return self._json("GET", "/api/mcp/status")

    def update_mcp_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/mcp/config", payload=fields, timeout=timeout)

    def save_settings_batch(
        self, payload: dict[str, Any], *, timeout: float = SETTINGS_SAVE_TIMEOUT
    ) -> dict[str, Any]:
        """一次性保存设置（单 HTTP 往返）。"""
        return self._json("POST", "/api/settings/save", payload=payload, timeout=timeout)

    def reload_mcp_config(self) -> dict[str, Any]:
        return self._json("POST", "/api/mcp/config/reload")

    def connect_mcp_server(self, server_id: str) -> dict[str, Any]:
        return self._json("POST", f"/api/mcp/servers/{server_id}/connect", timeout=180)

    def list_mcp_tools(self, *, connect: bool = True) -> dict[str, Any]:
        q = "true" if connect else "false"
        return self._json("GET", f"/api/mcp/tools?connect={q}", timeout=180)

    def stream_chat(
        self,
        message: str,
        history: list[ChatMessage],
        on_delta: Callable[[str], None] | None = None,
        *,
        on_agent_status: Callable[[str], None] | None = None,
        pet_expression_prompt: str | None = None,
        image_base64: str = "",
        image_mime: str = "image/png",
        image_analysis: str = "",
        cancel: threading.Event | None = None,
    ) -> StreamResult:
        payload: dict[str, Any] = {
            "message": message,
            "history": [{"role": m.role, "content": m.content} for m in history],
        }
        if pet_expression_prompt:
            payload["pet_expression_prompt"] = pet_expression_prompt
        if image_base64:
            payload["image_base64"] = image_base64
            payload["image_mime"] = image_mime or "image/png"
            if (image_analysis or "").strip():
                payload["image_analysis"] = image_analysis.strip()
        timeout = 240 if image_base64 else 120
        result = StreamResult()
        try:
            with self._http().post(
                f"{self.base_url}/api/chat/completions/stream",
                json=payload,
                stream=True,
                timeout=timeout,
            ) as resp:
                if not resp.ok:
                    result.error = _parse_http_error(resp)
                    return result
                # iter_lines 按行解析 SSE，避免 iter_content 整块缓冲导致无流式观感
                for line in resp.iter_lines(decode_unicode=True):
                    if cancel is not None and cancel.is_set():
                        break
                    if not line:
                        continue
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
                    agent_st = ev.get("agent_status")
                    if agent_st and on_agent_status:
                        on_agent_status(str(agent_st))
                    delta = ev.get("delta")
                    if delta:
                        result.text += delta
                        if on_delta:
                            on_delta(result.text)
                    if ev.get("done"):
                        return result
        except _req().RequestException as exc:
            result.error = str(exc)
        return result

    def synthesize_tts(
        self,
        text: str,
        *,
        text_lang: str | None = None,
        emotion_id: str | None = None,
        log_progress: bool | None = None,
        progress_label: str = "",
        terminal_bar: bool | None = None,
        cancel: threading.Event | None = None,
        on_progress: Callable[[str, int], None] | None = None,
    ) -> bytes:
        from pnn.pet.console_log import estimate_tts_wav_bytes

        def _ui(msg: str, pct: int) -> None:
            if on_progress is not None:
                on_progress(msg, pct)

        do_log = pet_console_verbose() if log_progress is None else bool(log_progress)
        use_bar = (
            bool(terminal_bar)
            if terminal_bar is not None
            else (tts_terminal_bar_enabled() and do_log)
        )
        bar = TtsTerminalBar() if use_bar else None
        label = (progress_label or "语音合成").strip()
        if emotion_id and emotion_id not in label:
            label = f"{label} [{emotion_id}]"
        estimate = estimate_tts_wav_bytes(text)
        t0 = time.monotonic()

        try:
            if bar:
                bar.start(label)
            elif do_log:
                log_tts("1/4", "检查 TTS 服务是否就绪")
            _ui("检查 TTS 服务…", 8)
            if bar:
                bar.update(6, "检查服务")
            if cancel is not None and cancel.is_set():
                raise InterruptedError("TTS 已取消")
            if not self.ensure_tts_ready(timeout=480.0):
                raise RuntimeError("TTS 服务未就绪（推理预热未完成，请稍候或重启 TTS）")
            preview = text.replace("\n", " ").strip()
            if len(preview) > 80:
                preview = preview[:80] + "…"
            if bar:
                bar.update(14, "提交请求")
            elif do_log:
                log_tts("2/4", f"提交合成请求（{len(text)} 字）{preview}")
            _ui(f"提交合成：{preview or '…'}", 18)
            payload: dict[str, Any] = {"text": text}
            if text_lang:
                payload["text_lang"] = text_lang
            if emotion_id:
                payload["emotion_id"] = emotion_id
            r = self._http().post(
                f"{self.base_url}/api/tts/synthesize",
                json=payload,
                timeout=300,
                stream=True,
            )
            if bar:
                bar.update(22, "推理中")
            elif do_log:
                log_tts("3/4", f"等待 GPT-SoVITS 推理（HTTP {r.status_code}）")
            _ui("GPT-SoVITS 推理合成中…", 32)
            if not r.ok:
                raise RuntimeError(_parse_http_error(r))
            chunks: list[bytes] = []
            last_ui = t0
            pulse_stop = threading.Event()

            def _bar_pulse() -> None:
                while not pulse_stop.wait(0.35):
                    if bar is None:
                        return
                    elapsed = time.monotonic() - t0
                    pct = 22 + min(20.0, elapsed * 1.2)
                    bar.update(pct, f"推理 {elapsed:.0f}s")

            pulse_thread: threading.Thread | None = None
            if bar:
                pulse_thread = threading.Thread(
                    target=_bar_pulse, name="pet-tts-bar-pulse", daemon=True
                )
                pulse_thread.start()
            for chunk in r.iter_content(chunk_size=65536):
                if cancel is not None and cancel.is_set():
                    r.close()
                    raise InterruptedError("TTS 已取消")
                if not chunk:
                    continue
                chunks.append(chunk)
                now = time.monotonic()
                total = sum(len(c) for c in chunks)
                if bar:
                    recv_pct = min(1.0, total / estimate)
                    pct = 42 + 53 * recv_pct
                    bar.update(min(95.0, pct), f"{total // 1024} KB")
                if on_progress is not None and now - last_ui >= 0.25:
                    pct_ui = min(92, 32 + int((now - t0) * 10) + min(30, total // 8000))
                    _ui(f"接收音频 {total // 1024} KB · {now - t0:.1f}s", pct_ui)
                    last_ui = now
            pulse_stop.set()
            if pulse_thread is not None:
                pulse_thread.join(timeout=0.5)
            data = b"".join(chunks)
            if bar:
                bar.finish(f"{len(data) // 1024} KB · {time.monotonic() - t0:.1f}s")
            elif do_log:
                log_tts(
                    "4/4",
                    f"合成完成，音频 {len(data)} 字节，总耗时 {time.monotonic() - t0:.1f}s",
                )
            _ui("合成完成，准备播放", 100)
            return data
        except Exception:
            if bar:
                bar.abort()
            raise

    def asr_stream_start(self) -> dict[str, Any]:
        return self._json("POST", "/api/stream/start", timeout=30)

    def asr_stream_stop(self) -> None:
        try:
            self._http().post(f"{self.base_url}/api/stream/stop", timeout=10)
        except _req().RequestException:
            pass
