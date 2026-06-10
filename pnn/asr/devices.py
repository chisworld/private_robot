"""系统麦克风枚举与打开探测（sounddevice / PortAudio）。"""

from __future__ import annotations

import threading
import time
from typing import Any

_DEVICES_CACHE_TTL = 10.0
_devices_lock = threading.RLock()
_devices_cache: tuple[float, list[dict[str, Any]]] | None = None


def invalidate_input_devices_cache() -> None:
    global _devices_cache
    with _devices_lock:
        _devices_cache = None


def list_input_devices(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    global _devices_cache
    now = time.monotonic()
    with _devices_lock:
        if (
            not force_refresh
            and _devices_cache is not None
            and now - _devices_cache[0] < _DEVICES_CACHE_TTL
        ):
            return [dict(item) for item in _devices_cache[1]]
        devices = _list_input_devices_uncached()
        _devices_cache = (now, devices)
        return [dict(item) for item in devices]


def _list_input_devices_uncached() -> list[dict[str, Any]]:
    import sounddevice as sd

    default_in: int | None = None
    try:
        pair = sd.default.device
        if pair and pair[0] is not None and int(pair[0]) >= 0:
            default_in = int(pair[0])
    except Exception:
        default_in = None

    out: list[dict[str, Any]] = []
    try:
        all_devs = sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"无法枚举音频设备: {exc}") from exc

    for idx, dev in enumerate(all_devs):
        if int(dev.get("max_input_channels", 0)) < 1:
            continue
        hostapi = ""
        try:
            hostapi = str(sd.query_hostapis(dev["hostapi"])["name"])
        except Exception:
            hostapi = ""
        out.append(
            {
                "id": idx,
                "name": str(dev.get("name", f"设备 {idx}")),
                "hostapi": hostapi,
                "is_default": idx == default_in,
            }
        )
    return out


def resolve_input_device(device_id: int | None) -> int | None:
    """返回传给 sounddevice 的设备 ID；None 表示系统默认输入。"""
    import sounddevice as sd

    if device_id is not None:
        dev = sd.query_devices(device_id)
        if int(dev.get("max_input_channels", 0)) < 1:
            raise RuntimeError(f"所选设备（#{device_id}）不支持录音输入")
        return int(device_id)

    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    if default_in is not None and int(default_in) >= 0:
        try:
            dev = sd.query_devices(int(default_in))
            if int(dev.get("max_input_channels", 0)) >= 1:
                return None
        except Exception:
            pass

    for idx, dev in enumerate(sd.query_devices()):
        if int(dev.get("max_input_channels", 0)) >= 1:
            return int(idx)
    raise RuntimeError(
        "未找到可用麦克风。请在 Windows「设置 → 隐私 → 麦克风」中允许桌面应用访问，"
        "并在「声音 → 输入」里选择默认麦克风。"
    )


def device_label(device_id: int | None) -> str:
    if device_id is None:
        return "系统默认"
    import sounddevice as sd

    try:
        dev = sd.query_devices(device_id)
        return str(dev.get("name", f"设备 {device_id}"))
    except Exception:
        return f"设备 {device_id}"


def format_mic_open_error(exc: BaseException, device_id: int | None) -> str:
    msg = str(exc).strip() or type(exc).__name__
    lower = msg.lower()
    label = device_label(device_id)
    hints: list[str] = []
    if any(k in lower for k in ("permission", "access", "denied", "privilege")):
        hints.append("检查 Windows 隐私设置是否允许本应用使用麦克风")
    if any(k in lower for k in ("invalid device", "no input", "device unavailable", "-9996")):
        hints.append("在设置 → ASR 中重新选择麦克风设备")
    if any(k in lower for k in ("busy", "in use", "occupied", "-9985")):
        hints.append("关闭占用麦克风的其它软件（会议、录屏、浏览器标签页等）")
    if "sounddevice" in lower or "portaudio" in lower:
        hints.append("确认已安装 sounddevice（requirements.txt）")
    hint = "；".join(hints) if hints else "确认麦克风已插入并在系统声音设置中设为默认输入"
    return f"无法打开麦克风（{label}）: {msg}。{hint}"


def probe_microphone(
    device_id: int | None,
    *,
    samplerate: int = 16000,
    blocksize: int = 800,
) -> dict[str, Any]:
    """尝试打开输入流并立即关闭，用于启动前校验。"""
    import sounddevice as sd

    resolved = resolve_input_device(device_id)
    try:
        with sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            device=resolved,
        ):
            pass
    except Exception as exc:
        raise RuntimeError(format_mic_open_error(exc, device_id)) from exc
    return {
        "ok": True,
        "input_device": device_id,
        "resolved_device": resolved,
        "label": device_label(resolved if resolved is not None else device_id),
    }
