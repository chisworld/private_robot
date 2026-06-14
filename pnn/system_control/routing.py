"""判断用户是否在要求系统操控。"""

from __future__ import annotations

import re

# --- 分类关键词（尽量覆盖口语，但避免过宽误触） ---
_VOLUME_TERMS = (
    r"音量|声音|音频|喇叭|扬声器|系统音|媒体音|"
    r"静音|取消静音|解除静音|关静音|开静音|"
    r"无声|有声|大声|小声|太吵|吵死了|"
    r"安静(?:点|一下|些|一点)?|响(?:一点|些|点)?|轻(?:一点|些|点)?|"
    r"听不见|听不到|开大声|关小声|"
    r"volume|mute|unmute|sound|audio"
)

_BRIGHTNESS_TERMS = (
    r"亮度|背光|屏幕亮度|显示器亮度|"
    r"屏幕(?:亮|暗|太亮|太暗|亮度)|显示器(?:亮|暗|亮度)|"
    r"太亮|太暗|刺眼|炫目|看不清|"
    r"亮(?:一点|些|点|度)?|暗(?:一点|些|点|度)?|"
    r"调亮|调暗|增亮|减暗|变亮|变暗|"
    r"brightness|backlight"
)

_RECYCLE_TERMS = (
    r"回收站|废纸篓|垃圾桶|"
    r"清空回收|清理回收|清回收|删回收|倒回收|"
    r"recycle\s*bin|trash\s*bin"
)

_POWER_TERMS = (
    r"关机|重启|重新启动|休眠|睡眠模式|待机|"
    r"关掉电脑|关闭电脑|电脑关机|系统关机|"
    r"shutdown|restart|reboot|power\s*off|sleep\s*mode"
)

_CANCEL_SHUTDOWN_TERMS = (
    r"取消(?:定时)?关机|别关机|不要关机|停止关机|撤销关机|"
    r"cancel\s*shutdown"
)

_MEDIA_TERMS = (
    r"播放|暂停|继续播|停播|开始播|停止播放|播放暂停|"
    r"下一首|下一曲|下一首歌|切歌|换一首|跳过这首|"
    r"上一首|上一曲|上一首歌|"
    r"qq音乐|QQ音乐|qqmusic"
)

_ACTION_VERBS = r"调|设|改|开|关|增|减|提|降|帮|请|弄"

_DIRECT_RE = re.compile(
    rf"(?:{_VOLUME_TERMS}|{_BRIGHTNESS_TERMS}|{_RECYCLE_TERMS}|{_POWER_TERMS}|"
    rf"{_CANCEL_SHUTDOWN_TERMS}|{_MEDIA_TERMS})",
    re.IGNORECASE,
)

_COMPOUND_RES = (
    re.compile(
        rf"(?:{_ACTION_VERBS}).{{0,12}}(?:{_VOLUME_TERMS}|{_BRIGHTNESS_TERMS})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:{_VOLUME_TERMS}|{_BRIGHTNESS_TERMS}|{_RECYCLE_TERMS}).{{0,12}}"
        rf"(?:{_ACTION_VERBS}|一点|一些|一下)",
        re.IGNORECASE,
    ),
)

_SHUTDOWN_RE = re.compile(
    r"(?:"
    r"(?:\d+|半|一|两|三|四|五|六|七|八|九|十|几|半个?).{0,6}(?:分钟|小时|min|mins).{0,10}(?:后|之后)?(?:关机|重启)"
    r"|(?:关机|重启).{0,10}(?:\d+|半|一|两|三|四|五|十|几).{0,6}(?:分钟|小时|min|mins)"
    r"|(?:一会儿|一会|待会|稍后|马上|立刻|现在).{0,6}(?:关机|重启)"
    r")",
    re.IGNORECASE,
)

_CANCEL_SHUTDOWN_RE = re.compile(
    rf"(?:{_CANCEL_SHUTDOWN_TERMS})",
    re.IGNORECASE,
)

_BRIGHTNESS_TOPIC_RE = re.compile(
    rf"(?:{_BRIGHTNESS_TERMS})",
    re.IGNORECASE,
)

_VOLUME_TOPIC_RE = re.compile(
    rf"(?:{_VOLUME_TERMS})",
    re.IGNORECASE,
)

_BRIGHTNESS_ABS_RE = re.compile(
    r"(?:亮度|背光|屏幕(?:亮度)?|显示器(?:亮度)?)"
    r".{0,10}(?:调到|调至|设为|设置|改成|改为|到|为)\s*(\d+)\s*%?",
    re.IGNORECASE,
)
_BRIGHTNESS_UP_RE = re.compile(
    r"(?:亮度|背光|屏幕|显示器)"
    r".{0,8}(?:调高|调亮|增亮|变亮|提高|加|亮)\s*(\d+)",
    re.IGNORECASE,
)
_BRIGHTNESS_UP_BARE_RE = re.compile(
    r"(?:亮度|背光|屏幕|显示器).{0,8}(?:调高|调亮|增亮|变亮|一点|一些|一下)",
    re.IGNORECASE,
)
_BRIGHTNESS_DOWN_RE = re.compile(
    r"(?:亮度|背光|屏幕|显示器)"
    r".{0,8}(?:调低|调暗|减暗|变暗|降低|减|暗)\s*(\d+)",
    re.IGNORECASE,
)
_BRIGHTNESS_DOWN_BARE_RE = re.compile(
    r"(?:亮度|背光|屏幕|显示器).{0,8}(?:调低|调暗|减暗|变暗|一点|一些|一下)",
    re.IGNORECASE,
)
# 口语：「太亮了，暗一点」
_BRIGHTNESS_INFORMAL_UP_RE = re.compile(
    r"太暗|看不清|暗(?:一点|些|点|一下)",
    re.IGNORECASE,
)
_BRIGHTNESS_INFORMAL_DOWN_RE = re.compile(
    r"太亮|刺眼|炫目|亮(?:一点|些|点|一下)",
    re.IGNORECASE,
)

_VOLUME_ABS_RE = re.compile(
    r"(?:音量|声音|音频).{0,10}(?:调到|调至|设为|设置|改成|改为|到|为)\s*(\d+)\s*%?",
    re.IGNORECASE,
)
_VOLUME_UP_DELTA_RE = re.compile(
    r"(?:音量|声音|音频).{0,10}(?:调大|开大|增大|提高|加|响)\s*(\d+)",
    re.IGNORECASE,
)
_VOLUME_DOWN_DELTA_RE = re.compile(
    r"(?:音量|声音|音频).{0,10}(?:调小|关小|减小|降低|减|轻)\s*(\d+)",
    re.IGNORECASE,
)
_VOLUME_UP_BARE_RE = re.compile(
    r"(?:音量|声音|音频|太吵|吵).{0,8}(?:调大|开大|增大|提高|响|大声|一点|一些|一下)",
    re.IGNORECASE,
)
_VOLUME_DOWN_BARE_RE = re.compile(
    r"(?:音量|声音|音频).{0,8}(?:调小|关小|减小|降低|轻|小声|一点|一些|一下)|"
    r"安静(?:点|一下|些|一点)?|太吵|吵死了",
    re.IGNORECASE,
)
_MUTE_RE = re.compile(
    r"静音|关(?:掉)?声音|无声|mute",
    re.IGNORECASE,
)
_UNMUTE_RE = re.compile(
    r"取消静音|解除静音|开(?:声音|有声)|unmute",
    re.IGNORECASE,
)

_MEDIA_TOPIC_RE = re.compile(rf"(?:{_MEDIA_TERMS})", re.IGNORECASE)

# 用户聊到 QQ 音乐时自动对焦客户端（不限于播放/切歌指令）
_QQ_MUSIC_TOPIC_RE = re.compile(
    r"qq\s*音乐|qq\s*music|QQMusic|qqmusic",
    re.IGNORECASE,
)

_MEDIA_NEXT_RE = re.compile(
    r"下一首|下一曲|下一首歌|切歌|换一首|跳过(?:这)?首|next\s*track",
    re.IGNORECASE,
)
_MEDIA_PREV_RE = re.compile(
    r"上一首|上一曲|上一首歌|previous\s*track",
    re.IGNORECASE,
)
_MEDIA_PLAY_PAUSE_RE = re.compile(
    r"(?:"
    r"播放(?:音乐|歌曲|qq音乐|QQ音乐)?|"
    r"暂停(?:播放|音乐|歌曲)?|继续播放|继续播|停播|开始播|停止播放|播放暂停|"
    r"play|pause|toggle\s*play"
    r")",
    re.IGNORECASE,
)


def needs_system_control_task(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _SHUTDOWN_RE.search(raw):
        return True
    if _CANCEL_SHUTDOWN_RE.search(raw):
        return True
    if _DIRECT_RE.search(raw):
        return True
    return any(p.search(raw) for p in _COMPOUND_RES)


def parse_brightness_adjustment(text: str) -> dict[str, int] | None:
    """从口语解析亮度调节：调高8 → {delta: 8}；调到80 → {percent: 80}。"""
    raw = (text or "").strip()
    if not raw or not _BRIGHTNESS_TOPIC_RE.search(raw):
        return None
    m = _BRIGHTNESS_ABS_RE.search(raw)
    if m:
        return {"percent": max(0, min(100, int(m.group(1))))}
    m = _BRIGHTNESS_UP_RE.search(raw)
    if m:
        return {"delta": int(m.group(1))}
    m = _BRIGHTNESS_DOWN_RE.search(raw)
    if m:
        return {"delta": -int(m.group(1))}
    if _BRIGHTNESS_UP_BARE_RE.search(raw) or _BRIGHTNESS_INFORMAL_UP_RE.search(raw):
        return {"delta": 10}
    if _BRIGHTNESS_DOWN_BARE_RE.search(raw) or _BRIGHTNESS_INFORMAL_DOWN_RE.search(raw):
        return {"delta": -10}
    return None


def parse_volume_adjustment(text: str) -> dict[str, int] | str | None:
    """解析音量：调到20 → {percent:20}；太吵 → {hint:'up'}；静音 → 'mute'。"""
    raw = (text or "").strip()
    if not raw or not _VOLUME_TOPIC_RE.search(raw):
        return None
    if _UNMUTE_RE.search(raw):
        return "unmute"
    if _MUTE_RE.search(raw) and not _UNMUTE_RE.search(raw):
        return "mute"
    m = _VOLUME_ABS_RE.search(raw)
    if m:
        return {"percent": max(0, min(100, int(m.group(1))))}
    m = _VOLUME_UP_DELTA_RE.search(raw)
    if m:
        return {"delta": int(m.group(1))}
    m = _VOLUME_DOWN_DELTA_RE.search(raw)
    if m:
        return {"delta": -int(m.group(1))}
    if _VOLUME_UP_BARE_RE.search(raw):
        return {"hint": "up"}
    if _VOLUME_DOWN_BARE_RE.search(raw):
        return {"hint": "down"}
    return None


def mentions_qq_music_topic(text: str) -> bool:
    """消息是否涉及 QQ 音乐（用于自动对焦窗口）。"""
    return bool(_QQ_MUSIC_TOPIC_RE.search((text or "").strip()))


def parse_media_control(text: str) -> str | None:
    """解析 QQ 音乐播放操控：play_pause | next | previous。"""
    raw = (text or "").strip()
    if not raw or not _MEDIA_TOPIC_RE.search(raw):
        return None
    if _MEDIA_NEXT_RE.search(raw):
        return "next"
    if _MEDIA_PREV_RE.search(raw):
        return "previous"
    if _MEDIA_PLAY_PAUSE_RE.search(raw):
        return "play_pause"
    return None


def build_system_control_agent_mandate(user_message: str) -> str:
    """把口语指令落成明确的工具参数。"""
    if not needs_system_control_task(user_message):
        return ""
    lines = ["【本轮系统操控·必须调用工具，勿假装已执行】"]

    adj = parse_brightness_adjustment(user_message)
    if adj:
        if "percent" in adj:
            p = adj["percent"]
            lines.append(
                f"用户要求把亮度设为 {p}%，请调用 local__set_brightness，参数 percent={p}。"
            )
        else:
            d = adj["delta"]
            lines.append(
                f"用户要求相对调节亮度（{'+' if d > 0 else ''}{d}），"
                f"请调用 local__set_brightness，参数 delta={d}。"
            )

    vol = parse_volume_adjustment(user_message)
    if vol == "mute":
        lines.append("用户要求静音，请调用 local__set_volume，参数 percent=0。")
    elif vol == "unmute":
        lines.append("用户要求取消静音，请调用 local__set_volume，参数 percent=30 或合适值。")
    elif isinstance(vol, dict):
        if "percent" in vol:
            p = vol["percent"]
            lines.append(
                f"用户要求把音量设为 {p}%，请调用 local__set_volume，参数 percent={p}。"
            )
        elif "delta" in vol:
            d = vol["delta"]
            lines.append(
                f"用户要求相对调节音量（{'+' if d > 0 else ''}{d}），"
                f"请调用 local__set_volume，参数 delta={d}。"
            )
        elif vol.get("hint") == "up":
            lines.append(
                "用户要求增大音量，请调用 local__set_volume，参数 delta=10。"
            )
        elif vol.get("hint") == "down":
            lines.append(
                "用户要求减小音量，请调用 local__set_volume，参数 delta=-10。"
            )

    media = parse_media_control(user_message)
    if media == "play_pause":
        lines.append(
            "用户要求播放/暂停 QQ 音乐，请调用 local__media_control，"
            '参数 action="play_pause"。'
        )
    elif media == "next":
        lines.append(
            '用户要求下一首，请调用 local__media_control，参数 action="next"。'
        )
    elif media == "previous":
        lines.append(
            '用户要求上一首，请调用 local__media_control，参数 action="previous"。'
        )

    if re.search(rf"(?:{_RECYCLE_TERMS})", user_message, re.IGNORECASE):
        lines.append("请调用 local__empty_recycle_bin。")
    if _CANCEL_SHUTDOWN_RE.search(user_message):
        lines.append("请调用 local__cancel_shutdown。")
    elif _SHUTDOWN_RE.search(user_message):
        lines.append(
            "用户要求定时关机/重启，请调用 local__schedule_shutdown，"
            "minutes 填用户说的分钟数（至少满足安全限制）。"
        )
    if len(lines) <= 1:
        lines.append("请根据用户原话选择正确的 local__ 系统工具并调用。")
    return "\n".join(lines)
