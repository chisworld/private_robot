"""PNN Garden API 客户端（8765）：LLM 流式、TTS、ASR、配置。"""

from __future__ import annotations

import json
import logging
import os
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
# 设置页拉配置：API 正忙 TTS 预热时 thread pool 可能排队，单接口不宜过长
SETTINGS_LOAD_TIMEOUT = 15.0
# TTS 预热/启动为后台任务，HTTP 仅确认已受理
TTS_KICK_TIMEOUT = 4.0
# API 忙时 /api/tts/health 可能排队，过短易误判为离线并触发重试
TTS_HEALTH_TIMEOUT = 12.0

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


def _sanitize_chat_history(history: list[ChatMessage]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for item in history:
        role = (item.role or "").strip()
        content = (item.content or "").strip()
        if role in ("user", "assistant") and content:
            out.append(ChatMessage(role=role, content=content))
    return out


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
        self._tts_warm_until = 0.0

    def _http(self):
        if self._session is None:
            self._session = _req().Session()
        return self._session

    def reset_http(self) -> None:
        """超时/断连后丢弃旧连接，避免 CLOSE_WAIT 堆积。"""
        if self._session is not None:
            try:
                self._session.close()
            except _req().RequestException:
                pass
            self._session = None

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
            h = self.tts_health(timeout=min(TTS_HEALTH_TIMEOUT, interval + 2.0))
            if h.get("ok"):
                return True
            time.sleep(interval)
        return False

    def tts_server_online(self, *, timeout: float = TTS_HEALTH_TIMEOUT) -> bool:
        """GPT-SoVITS HTTP 已监听（不要求 inference_ready）。"""
        return bool(self.tts_health(timeout=timeout).get("server_alive"))

    def kick_tts_warmup(self) -> None:
        """非阻塞：请求 API 执行 TTS preload（配置已加载 + 后台起 9880）。"""
        if self.wait_tts_ready(timeout=2.0):
            return
        try:
            self._json(
                "POST",
                "/api/tts/preload",
                payload={},
                timeout=TTS_KICK_TIMEOUT,
            )
        except _req().Timeout:
            logger.info(
                "TTS preload 已提交后台（GPT-SoVITS 加载约 1～8 分钟，请稍候）"
            )
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
                logger.debug("TTS 回退启动: %s", exc2)

    def start_tts_server(self) -> dict[str, Any]:
        try:
            return self._json(
                "POST",
                "/api/tts/server/start",
                payload={},
                timeout=TTS_KICK_TIMEOUT,
            )
        except _req().Timeout:
            logger.info("TTS 启动已提交后台")
            return {"ok": False, "status": "starting", "accepted": True}
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

    def ensure_tts_ready(
        self,
        timeout: float = 480.0,
        *,
        on_progress: Callable[[str, int], None] | None = None,
        require_inference: bool = False,
        kick_warmup: bool = True,
    ) -> bool:
        """require_inference=True：后台预热用，须等推理试合成完成。
        require_inference=False：对话合成用，短暂等待后 HTTP 在线即可提交（由 API 侧加载）。"""

        def _progress(msg: str, pct: int) -> None:
            if on_progress is not None:
                on_progress(msg, pct)

        if time.monotonic() < self._tts_warm_until:
            h = self.tts_health(timeout=TTS_HEALTH_TIMEOUT)
            if h.get("ok") or (not require_inference and h.get("server_alive")):
                return True
            self._tts_warm_until = 0.0

        quick = min(12.0, timeout) if not require_inference else min(8.0, timeout)
        if self.wait_tts_ready(timeout=quick):
            self._tts_warm_until = time.monotonic() + 120.0
            return True

        if kick_warmup:
            self.kick_tts_warmup()

        deadline = time.monotonic() + timeout
        t0 = time.monotonic()
        while time.monotonic() < deadline:
            h = self.tts_health(timeout=TTS_HEALTH_TIMEOUT)
            if h.get("ok"):
                self._tts_warm_until = time.monotonic() + 120.0
                return True
            if not require_inference and h.get("server_alive") and not h.get("warming"):
                logger.debug(
                    "TTS HTTP 已在线，提交合成（推理预热=%s）",
                    h.get("inference_ready"),
                )
                return True

            elapsed = int(time.monotonic() - t0)
            if h.get("warming") or (
                h.get("server_alive") and not h.get("inference_ready")
            ):
                _progress(
                    f"TTS 首次加载模型中… 已等待 {elapsed}s（约 1～8 分钟）",
                    min(17, 10 + elapsed // 15),
                )
            elif not h.get("server_alive"):
                _progress(f"等待 TTS 服务启动… {elapsed}s", min(12, 8 + elapsed // 20))

            err = str(h.get("error") or "")
            if "超时" in err or "timeout" in err.lower():
                logger.debug("TTS health 响应慢（API 可能正忙），继续等待")
            time.sleep(2.0 if require_inference else 1.0)

        if not require_inference and self.tts_server_online(timeout=TTS_HEALTH_TIMEOUT):
            return True

        if not self.tts_server_online(timeout=TTS_HEALTH_TIMEOUT):
            self.start_tts_server()
            if self.wait_tts_ready(timeout=min(120.0, timeout)):
                self._tts_warm_until = time.monotonic() + 120.0
                return True
            from pnn.pet.tts_local import start_local_server

            ok = start_local_server(wait_ready=True, timeout=timeout)
            if ok:
                self._tts_warm_until = time.monotonic() + 120.0
            return ok if require_inference else ok or self.tts_server_online()
        return False

    def get_chat_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/chat/config", timeout=timeout)

    def reload_chat_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("POST", "/api/chat/config/reload", timeout=timeout)

    def update_chat_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/chat/config", payload=fields, timeout=timeout)

    def list_characters(self, *, timeout: float = 30) -> list[dict[str, Any]]:
        data = self._json("GET", "/api/chat/characters", timeout=timeout)
        return data.get("characters", [])

    def set_active_character(self, char_id: str) -> dict[str, Any]:
        return self.update_chat_config(active_character=char_id)

    def list_character_packs(self, *, timeout: float = 30) -> list[dict[str, Any]]:
        data = self._json("GET", "/api/characters/packs", timeout=timeout)
        return data.get("items", [])

    def get_character_pack(self, char_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/characters/packs/{char_id}")

    def save_character_pack(
        self, char_id: str, *, timeout: float = 30, **fields: Any
    ) -> dict[str, Any]:
        return self._json(
            "PUT", f"/api/characters/packs/{char_id}", payload=fields, timeout=timeout
        )

    def apply_character_pack(self, char_id: str, *, timeout: float = 45) -> dict[str, Any]:
        return self._json(
            "POST", f"/api/characters/packs/{char_id}/apply", timeout=timeout
        )

    def apply_character_pack_if_needed(
        self, char_id: str, *, timeout: float = 45
    ) -> bool:
        """启动时应用角色包；同 ID 但 pack.json 已改仍会重载。"""
        cid = char_id.strip()
        if not cid:
            return False
        try:
            from pnn.characters.pack import pack_path
            from pnn.characters.service import character_pack_service

            path = pack_path(cid)
            mtime = path.stat().st_mtime if path.is_file() else 0.0
            active = character_pack_service.get_active_id()
            cached_mtime = character_pack_service._applied_pack_mtime.get(cid)
            if active == cid and cached_mtime == mtime and mtime > 0:
                return False
            character_pack_service.apply_pack(cid, persist_llm=True, schedule_warm=True)
            return True
        except Exception:
            try:
                self.apply_character_pack(cid, timeout=timeout)
                return True
            except _req().RequestException:
                return False

    def get_memory_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/memory/config", timeout=timeout)

    def update_memory_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/memory/config", payload=fields, timeout=timeout)

    def list_memories(
        self,
        limit: int = 50,
        *,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        kind: str | None = None,
        timeout: float = 30,
    ) -> list[dict[str, Any]]:
        params: list[str] = [f"limit={limit}"]
        if q:
            from urllib.parse import quote

            params.append(f"q={quote(q)}")
        if date_from:
            params.append(f"date_from={date_from}")
        if date_to:
            params.append(f"date_to={date_to}")
        if kind:
            from urllib.parse import quote

            params.append(f"kind={quote(kind)}")
        query = "&".join(params)
        data = self._json("GET", f"/api/memory/list?{query}", timeout=timeout)
        return data.get("items", [])

    def get_memory_stats(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/memory/stats", timeout=timeout)

    def list_dialogue_history(
        self, limit: int = 500, *, days: int = 60, timeout: float = 60
    ) -> list[dict[str, Any]]:
        params = f"limit={limit}&days={days}"
        data = self._json("GET", f"/api/memory/dialogue-history?{params}", timeout=timeout)
        return data.get("items", [])

    def delete_memory(self, memory_id: str) -> None:
        self._json("DELETE", f"/api/memory/{memory_id}")

    def delete_dialogue_history_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self._json(
            "DELETE",
            "/api/memory/dialogue-history",
            payload=entry,
            timeout=60,
        )

    def migrate_memory_japanese_to_chinese(self) -> dict[str, Any]:
        return self._json("POST", "/api/memory/migrate-japanese-to-chinese", timeout=300)

    def get_translate_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/translate/config", timeout=timeout)

    def update_translate_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/translate/config", payload=fields, timeout=timeout)

    def translate_text(self, text: str) -> str:
        data = self._json("POST", "/api/translate", payload={"text": text})
        return str(data.get("text", text))

    def get_tts_config(
        self, *, fresh: bool = False, probe: bool = True, timeout: float = 30
    ) -> dict[str, Any]:
        parts: list[str] = []
        if fresh:
            parts.append("fresh=1")
        if not probe:
            parts.append("probe=0")
        query = f"?{'&'.join(parts)}" if parts else ""
        return self._json("GET", f"/api/tts/config{query}", timeout=timeout)

    def update_tts_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/tts/config", payload=fields, timeout=timeout)

    def get_asr_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/config", timeout=timeout)

    def update_asr_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/config", payload=fields, timeout=timeout)

    def list_asr_input_devices(self, *, timeout: float = 15) -> list[dict[str, Any]]:
        data = self._json("GET", "/api/audio/input-devices", timeout=timeout)
        return list(data.get("devices") or [])

    def get_mcp_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/mcp/config", timeout=timeout)

    def get_launch_apps_config(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/launch-apps/config", timeout=timeout)

    def update_launch_apps_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/launch-apps/config", payload=fields, timeout=timeout)

    def export_character_pack(self, char_id: str, *, timeout: float = 120) -> bytes:
        import requests

        url = f"{self.base_url}/api/characters/packs/{char_id.strip()}/export"
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content

    def import_character_pack(
        self,
        data: bytes,
        *,
        new_id: str | None = None,
        overwrite: bool = False,
        timeout: float = 120,
    ) -> dict[str, Any]:
        import requests

        url = f"{self.base_url}/api/characters/packs/import"
        params: dict[str, str | bool] = {"overwrite": overwrite}
        if new_id:
            params["new_id"] = new_id
        files = {"file": ("character-pack.zip", data, "application/zip")}
        resp = requests.post(url, params=params, files=files, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def get_mcp_status(self, *, timeout: float = 30) -> dict[str, Any]:
        return self._json("GET", "/api/mcp/status", timeout=timeout)

    def update_mcp_config(self, *, timeout: float = 30, **fields: Any) -> dict[str, Any]:
        return self._json("PUT", "/api/mcp/config", payload=fields, timeout=timeout)

    def save_settings_batch(
        self, payload: dict[str, Any], *, timeout: float = SETTINGS_SAVE_TIMEOUT
    ) -> dict[str, Any]:
        """一次性保存设置（单 HTTP 往返）。"""
        return self._json("POST", "/api/settings/save", payload=payload, timeout=timeout)

    def reload_mcp_config(self) -> dict[str, Any]:
        return self._json("POST", "/api/mcp/config/reload")

    def reconnect_filesystem_mcp(self, *, timeout: float = 120) -> dict[str, Any]:
        return self._json("POST", "/api/mcp/servers/filesystem/reconnect", timeout=timeout)

    def connect_mcp_server(self, server_id: str) -> dict[str, Any]:
        return self._json("POST", f"/api/mcp/servers/{server_id}/connect", timeout=180)

    def list_mcp_tools(self, *, connect: bool = True) -> dict[str, Any]:
        q = "true" if connect else "false"
        return self._json("GET", f"/api/mcp/tools?connect={q}", timeout=180)

    def _stream_chat_once(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        on_delta: Callable[[str], None] | None,
        on_agent_status: Callable[[str], None] | None,
        on_weather_status: Callable[[str], None] | None,
        on_llm_route: Callable[[dict[str, Any]], None] | None,
        cancel: threading.Event | None,
    ) -> StreamResult:
        result = StreamResult()
        local_route = False
        route_at: float | None = None
        got_delta = False
        try:
            first_token_timeout = float(
                os.getenv("LOCAL_CHAT_FIRST_TOKEN_TIMEOUT", "180")
            )
        except ValueError:
            first_token_timeout = 180.0
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
                resp.encoding = "utf-8"
                for line in resp.iter_lines(decode_unicode=True):
                    if cancel is not None and cancel.is_set():
                        break
                    if (
                        local_route
                        and not got_delta
                        and route_at is not None
                        and first_token_timeout > 0
                        and time.monotonic() - route_at > first_token_timeout
                    ):
                        result.error = (
                            f"本地 Qwen 首 token 超时（>{int(first_token_timeout)}s）。"
                            "请查看 llama-server/GPU 是否卡住，或重启桌宠。"
                        )
                        return result
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
                        try:
                            on_agent_status(str(agent_st))
                        except Exception as exc:
                            logger.debug("agent_status callback: %s", exc)
                    wx_st = ev.get("weather_status")
                    if wx_st and on_weather_status:
                        try:
                            on_weather_status(str(wx_st))
                        except Exception as exc:
                            logger.debug("weather_status callback: %s", exc)
                    route = ev.get("llm_route")
                    if route and on_llm_route:
                        route_obj: dict[str, Any]
                        if isinstance(route, dict):
                            route_obj = route
                        else:
                            try:
                                route_obj = json.loads(str(route))
                            except json.JSONDecodeError:
                                route_obj = {"route": str(route)}
                        local_route = str(route_obj.get("route") or "") == "local_qwen"
                        if route_at is None:
                            route_at = time.monotonic()
                        try:
                            on_llm_route(route_obj)
                        except Exception as exc:
                            logger.debug("llm_route callback: %s", exc)
                    delta = ev.get("delta")
                    if delta:
                        got_delta = True
                        result.text += delta
                        if on_delta:
                            try:
                                on_delta(result.text)
                            except Exception as exc:
                                logger.warning("on_delta callback failed: %s", exc)
                    if ev.get("done"):
                        return result
        except _req().RequestException as exc:
            result.error = str(exc)
        except Exception as exc:
            result.error = str(exc) or "对话流式读取失败"
        return result

    @staticmethod
    def _should_retry_stream(error: str | None) -> bool:
        if not error:
            return False
        low = error.lower()
        return "timed out" in low or "timeout" in low or "connection" in low

    def stream_chat(
        self,
        message: str,
        history: list[ChatMessage],
        on_delta: Callable[[str], None] | None = None,
        *,
        on_agent_status: Callable[[str], None] | None = None,
        on_weather_status: Callable[[str], None] | None = None,
        on_llm_route: Callable[[dict[str, Any]], None] | None = None,
        pet_expression_prompt: str | None = None,
        image_base64: str = "",
        image_mime: str = "image/png",
        image_analysis: str = "",
        cancel: threading.Event | None = None,
        defer_memory: bool = False,
    ) -> StreamResult:
        payload: dict[str, Any] = {
            "message": message,
            "history": [
                {"role": m.role, "content": m.content}
                for m in _sanitize_chat_history(history)
            ],
        }
        if defer_memory:
            payload["defer_memory"] = True
        if pet_expression_prompt:
            payload["pet_expression_prompt"] = pet_expression_prompt
        if image_base64:
            payload["image_base64"] = image_base64
            payload["image_mime"] = image_mime or "image/png"
            if (image_analysis or "").strip():
                payload["image_analysis"] = image_analysis.strip()
        from pnn.core.env import getenv

        timeout = 600.0
        try:
            from pnn.llm.config_store import load_llm_config
            from pnn.llm.routing import local_llm_ready

            cfg = load_llm_config()
            if cfg.nsfw_enabled and local_llm_ready(cfg):
                timeout = 600.0
            else:
                base = getenv("DEEPSEEK_BASE_URL", "")
                local = "127.0.0.1" in base or "localhost" in base
                timeout = 600 if local else (240 if image_base64 else 120)
        except Exception:
            base = getenv("DEEPSEEK_BASE_URL", "")
            local = "127.0.0.1" in base or "localhost" in base
            timeout = 600 if local else (240 if image_base64 else 120)
        for attempt in range(2):
            if cancel is not None and cancel.is_set():
                return StreamResult()
            if attempt == 0:
                from pnn.pet.api_guard import ensure_api_before_chat

                if not ensure_api_before_chat():
                    return StreamResult(error="本地 API (8765) 无响应，自动恢复失败")
            result = self._stream_chat_once(
                payload,
                timeout=timeout,
                on_delta=on_delta,
                on_agent_status=on_agent_status,
                on_weather_status=on_weather_status,
                on_llm_route=on_llm_route,
                cancel=cancel,
            )
            if not self._should_retry_stream(result.error) or attempt > 0:
                return result
            self.reset_http()
            from pnn.pet.api_guard import recover_api_if_stuck

            if not recover_api_if_stuck(reason="LLM 流式超时"):
                return result
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
            if not self.ensure_tts_ready(
                timeout=15.0,
                on_progress=_ui,
                require_inference=False,
                kick_warmup=False,
            ):
                raise RuntimeError("TTS 服务未就绪（请稍候或重启 TTS）")
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
            wait_stop = threading.Event()
            if do_log and not bar:
                log_tts("3/4", "等待 GPT-SoVITS 推理（首次加载可能 1～8 分钟）")

            def _submit_wait_pulse() -> None:
                while not wait_stop.wait(0.5):
                    elapsed = time.monotonic() - t0
                    msg = f"GPT-SoVITS 推理中… {elapsed:.0f}s"
                    if bar:
                        bar.update(22 + min(18.0, elapsed * 0.4), f"推理 {elapsed:.0f}s")
                    _ui(msg, min(31, 22 + int(elapsed * 0.3)))

            wait_thread = threading.Thread(
                target=_submit_wait_pulse, name="pet-tts-submit-wait", daemon=True
            )
            wait_thread.start()
            try:
                r = self._http().post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload,
                    timeout=300,
                    stream=True,
                )
            finally:
                wait_stop.set()
                wait_thread.join(timeout=0.5)
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
            self._tts_warm_until = time.monotonic() + 120.0
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
