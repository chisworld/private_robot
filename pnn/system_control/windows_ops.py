"""Windows 系统操控实现（无额外 pip 依赖）。"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

_VK_VOLUME_MUTE = 0xAD
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_UP = 0xAF
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
# Windows 主音量通常约 50 档，每档约 2%
_VOLUME_STEPS = 50
_VOLUME_STEP_PERCENT = 100 / _VOLUME_STEPS


def _run_powershell(script: str, *, timeout: float = 30.0) -> str:
    if os.name != "nt":
        raise OSError("当前仅支持 Windows 系统操控")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"PowerShell 退出码 {proc.returncode}")
    return out


def _volume_key(vk: int, *, times: int = 1, delay: float = 0.015) -> None:
    if os.name != "nt":
        raise OSError("音量调节仅支持 Windows")
    user32 = ctypes.windll.user32
    flags_down = _KEYEVENTF_EXTENDEDKEY
    flags_up = _KEYEVENTF_EXTENDEDKEY | _KEYEVENTF_KEYUP
    for _ in range(max(1, int(times))):
        user32.keybd_event(vk, 0, flags_down, 0)
        user32.keybd_event(vk, 0, flags_up, 0)
        if delay > 0:
            time.sleep(delay)


def _percent_to_steps(percent: int) -> int:
    level = max(0, min(100, int(percent)))
    return max(0, min(_VOLUME_STEPS, round(level / _VOLUME_STEP_PERCENT)))


def _steps_for_delta(delta: int) -> int:
    return max(1, round(abs(int(delta)) / _VOLUME_STEP_PERCENT))


def _volume_via_keys_set_percent(percent: int) -> str:
    level = max(0, min(100, int(percent)))
    target_steps = _percent_to_steps(level)
    _volume_key(_VK_VOLUME_DOWN, times=_VOLUME_STEPS)
    if target_steps > 0:
        _volume_key(_VK_VOLUME_UP, times=target_steps)
    return f"已将系统音量设为约 {level}%（系统音量键模拟）"


def _volume_via_keys_adjust(delta: int) -> str:
    delta = max(-100, min(100, int(delta)))
    if delta == 0:
        return "音量未变化"
    steps = _steps_for_delta(delta)
    if delta < 0:
        _volume_key(_VK_VOLUME_DOWN, times=steps)
        action = "降低"
    else:
        _volume_key(_VK_VOLUME_UP, times=steps)
        action = "提高"
    approx = steps * _VOLUME_STEP_PERCENT
    return f"已将系统音量{action}约 {approx:.0f}%（系统音量键模拟）"


_VOLUME_COM_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator {
  int NotImpl1();
  int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice {
  int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
}
[Guid("5CDF2C82-841E-4546-9722-0AC074912141"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
  int f0(); int f1(); int f2(); int f3();
  int SetMasterVolumeLevelScalar(float level, System.Guid eventContext);
  int GetMasterVolumeLevelScalar(out float level);
}
[ComImport][Guid("BCDE0395-E52F-467C-8E3D-C456521039C0")]
public class MMDeviceEnumerator {}
'@
$devEnum = [IMMDeviceEnumerator][MMDeviceEnumerator]::new()
$device = $null
[void]$devEnum.GetDefaultAudioEndpoint(0, 1, [ref]$device)
$guid = [Guid]('5CDF2C82-841E-4546-9722-0AC074912141')
$vol = $null
[void]$device.Activate([ref]$guid, 23, [IntPtr]::Zero, [ref]$vol)
$audio = [IAudioEndpointVolume]$vol
{body}
"""


def _volume_via_com(body: str) -> str | None:
    try:
        return _run_powershell(_VOLUME_COM_SCRIPT.format(body=body))
    except Exception as exc:
        logger.debug("COM 音量调节不可用，改用音量键模拟: %s", exc)
        return None


def get_master_volume_percent() -> int | None:
    out = _volume_via_com(
        "$cur = 0.0\n"
        "[void]$audio.GetMasterVolumeLevelScalar([ref]$cur)\n"
        "Write-Output ([math]::Round($cur * 100))"
    )
    if out is None:
        return None
    try:
        return max(0, min(100, int(float(out.strip()))))
    except ValueError:
        return None


def set_master_volume_percent(percent: int) -> str:
    level = max(0, min(100, int(percent)))
    scalar = level / 100.0
    out = _volume_via_com(
        f"[void]$audio.SetMasterVolumeLevelScalar({scalar}, [Guid]::Empty)\n"
        "Write-Output 'ok'"
    )
    if out is not None:
        return f"已将系统音量设为 {level}%"
    return _volume_via_keys_set_percent(level)


def adjust_master_volume(delta_percent: int) -> str:
    delta = max(-100, min(100, int(delta_percent)))
    if delta == 0:
        return "音量未变化"
    cur = get_master_volume_percent()
    if cur is not None:
        target = max(0, min(100, cur + delta))
        return set_master_volume_percent(target)
    out = _volume_via_com(
        "$cur = 0.0\n"
        "[void]$audio.GetMasterVolumeLevelScalar([ref]$cur)\n"
        f"$next = [Math]::Max(0.0, [Math]::Min(1.0, $cur + ({delta} / 100.0)))\n"
        "[void]$audio.SetMasterVolumeLevelScalar($next, [Guid]::Empty)\n"
        "Write-Output ([math]::Round($next * 100))"
    )
    if out is not None:
        try:
            level = max(0, min(100, int(float(out.strip()))))
            return f"已将系统音量调整为约 {level}%"
        except ValueError:
            pass
    return _volume_via_keys_adjust(delta)


def adjust_brightness(delta_percent: int) -> str:
    """相对调节屏幕亮度（笔记本/外接屏支持情况因机器而异）。"""
    delta = max(-100, min(100, int(delta_percent)))
    ps = rf"""
$ErrorActionPreference = 'Stop'
$methods = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue
if (-not $methods) {{ throw '此设备不支持 WMI 亮度调节' }}
$cur = (Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness | Select-Object -First 1).CurrentBrightness
if ($null -eq $cur) {{ $cur = 50 }}
$next = [Math]::Max(0, [Math]::Min(100, $cur + {delta}))
$methods.WmiSetBrightness(1, $next) | Out-Null
Write-Output $next
"""
    out = _run_powershell(ps)
    return f"屏幕亮度已调整为约 {out.strip()}%"


def set_brightness_percent(percent: int) -> str:
    level = max(0, min(100, int(percent)))
    ps = rf"""
$ErrorActionPreference = 'Stop'
$methods = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue
if (-not $methods) {{ throw '此设备不支持 WMI 亮度调节' }}
$methods.WmiSetBrightness(1, {level}) | Out-Null
Write-Output 'ok'
"""
    _run_powershell(ps)
    return f"屏幕亮度已设为 {level}%"


def empty_recycle_bin() -> str:
    if os.name != "nt":
        raise OSError("回收站清空仅支持 Windows")
    flags = 0x00000001 | 0x00000002 | 0x00000004  # SHERB_NOCONFIRMATION | NOPROGRESSUI | NOSOUND
    rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    if rc != 0:
        raise RuntimeError(f"清空回收站失败，错误码 {rc}")
    return "已清空回收站"


def schedule_shutdown(minutes: int) -> str:
    if os.name != "nt":
        raise OSError("定时关机仅支持 Windows")
    sec = max(60, int(minutes) * 60)
    proc = subprocess.run(
        ["shutdown", "/s", "/t", str(sec)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "shutdown 失败").strip())
    return f"已计划在 {int(minutes)} 分钟后关机（可用 cancel_shutdown 取消）"


def cancel_shutdown() -> str:
    if os.name != "nt":
        raise OSError("取消关机仅支持 Windows")
    proc = subprocess.run(
        ["shutdown", "/a"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "取消失败").strip())
    return "已取消计划关机"


_VK_SPACE = 0x20
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_LEFT = 0x25
_VK_RIGHT = 0x27
_SW_RESTORE = 9

_QQMUSIC_TITLE_HINTS = ("QQ音乐", "QQMusic", "qq music")


def _tap_key(vk: int, *, hold: float = 0.04) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    if hold > 0:
        time.sleep(hold)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def _chord(*keys: int, hold: float = 0.04) -> None:
    """依次按下修饰键与主键，再逆序释放。"""
    if len(keys) < 1:
        return
    user32 = ctypes.windll.user32
    mods = keys[:-1]
    main = keys[-1]
    for vk in mods:
        user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(main, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(main, 0, _KEYEVENTF_KEYUP, 0)
    for vk in reversed(mods):
        user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def focus_qq_music_window(*, title_hints: tuple[str, ...] = _QQMUSIC_TITLE_HINTS) -> bool:
    """将 QQ 音乐主窗口置于前台（快捷键需焦点在客户端内）。"""
    if os.name != "nt":
        raise OSError("QQ 音乐操控仅支持 Windows")
    user32 = ctypes.windll.user32
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        low = title.casefold()
        for hint in title_hints:
            if hint.casefold() in low:
                matches.append(int(hwnd))
                break
        return True

    user32.EnumWindows(_enum_proc, 0)
    if not matches:
        return False
    hwnd = matches[0]
    user32.ShowWindow(hwnd, _SW_RESTORE)
    time.sleep(0.05)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.12)
    return bool(user32.GetForegroundWindow() == hwnd)


def send_qqmusic_play_pause_key() -> str:
    _tap_key(_VK_SPACE)
    return "已向 QQ 音乐发送播放/暂停（空格）"


def send_qqmusic_next_track_key() -> str:
    _chord(_VK_CONTROL, _VK_MENU, _VK_RIGHT)
    return "已向 QQ 音乐发送下一首（Ctrl+Alt+→）"


def send_qqmusic_previous_track_key() -> str:
    _chord(_VK_CONTROL, _VK_MENU, _VK_LEFT)
    return "已向 QQ 音乐发送上一首（Ctrl+Alt+←）"


def qqmusic_play_pause() -> str:
    if not focus_qq_music_window():
        return "未找到 QQ 音乐窗口，请先说「打开 QQ 音乐」"
    return send_qqmusic_play_pause_key()


def qqmusic_next_track() -> str:
    if not focus_qq_music_window():
        return "未找到 QQ 音乐窗口，请先说「打开 QQ 音乐」"
    return send_qqmusic_next_track_key()


def qqmusic_previous_track() -> str:
    if not focus_qq_music_window():
        return "未找到 QQ 音乐窗口，请先说「打开 QQ 音乐」"
    return send_qqmusic_previous_track_key()
