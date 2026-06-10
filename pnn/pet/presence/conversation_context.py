"""空闲搭话用的近期对话与沉默情境说明（供模型读上下文，非禁令列表）。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from pnn.pet.presence.models import SessionPresenceBundle

_CLIP = 220
_TURN_CLIP = 120
_RECENT_TURNS_FOR_IDLE = 10
_TOPIC_SCAN_TURNS = 20

_MEAL_TOPIC_RE = re.compile(
    r"(?:吃饭|用餐|开饭|做了.{0,8}菜|色香味|开动|ご飯|食事|夕飯|いただき|ごちそうさま|食べ)",
    re.IGNORECASE,
)


def _clip(text: str, limit: int = _CLIP) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def _load_recent_turns(session_key: str, limit: int = 3) -> list[tuple[str, str]]:
    sk = (session_key or "").strip()
    if not sk:
        return []
    try:
        from pnn.pet.presence.daily_log import _log_path

        path = _log_path(sk)
        if not path.is_file():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        turns: list[tuple[str, str]] = []
        for item in raw[-limit:]:
            if not isinstance(item, dict):
                continue
            user = _clip(str(item.get("user") or ""), _TURN_CLIP)
            assistant = _clip(str(item.get("assistant") or ""), _TURN_CLIP)
            if user or assistant:
                turns.append((user, assistant))
        return turns
    except Exception:
        return []


def has_recent_conversation(
    bundle: SessionPresenceBundle,
    session_key: str = "",
    *,
    max_age_hours: float = 6.0,
    now: datetime | None = None,
) -> bool:
    """同一会话在 max_age_hours 内有过对话（daily_log 或 state 末句）。"""
    ts = now or datetime.now()
    cutoff = ts - timedelta(hours=max(0.5, float(max_age_hours)))
    sk = (session_key or bundle.state.session_key or "").strip()

    if _load_recent_turns(sk, limit=1):
        return True

    st = bundle.state
    if st.last_user_message.strip() or st.last_assistant_message.strip():
        if st.last_user_activity_at and st.last_user_activity_at >= cutoff:
            return True
    return False


def _conversation_blob(
    bundle: SessionPresenceBundle,
    session_key: str = "",
    *,
    turn_limit: int = _TOPIC_SCAN_TURNS,
) -> str:
    st = bundle.state
    sk = (session_key or st.session_key or "").strip()
    parts: list[str] = []
    for user, assistant in _load_recent_turns(sk, limit=turn_limit):
        if user:
            parts.append(user)
        if assistant:
            parts.append(assistant)
    if not parts:
        if st.last_user_message.strip():
            parts.append(st.last_user_message)
        if st.last_assistant_message.strip():
            parts.append(st.last_assistant_message)
    return " ".join(parts)


def build_topic_avoidance_hint(
    bundle: SessionPresenceBundle,
    session_key: str = "",
) -> str:
    """若近期已聊过某生活话题，提醒模型勿用同模板重复关心。"""
    blob = _conversation_blob(bundle, session_key)
    if not blob:
        return ""
    hints: list[str] = []
    if _MEAL_TOPIC_RE.search(blob):
        hints.append(
            "你们刚刚已经聊过吃饭/用餐（可能正在吃或刚吃完），"
            "勿再泛泛追问「有没有好好吃饭」「差不多到晚饭时间了」；"
            "应接续饭后或当前情境（游戏、亲昵、未说完的事等）。"
        )
    if not hints:
        return ""
    return "话题续接：" + " ".join(hints)


def build_recent_conversation_block(
    bundle: SessionPresenceBundle,
    session_key: str = "",
    *,
    turn_limit: int = _RECENT_TURNS_FOR_IDLE,
) -> str:
    st = bundle.state
    sk = (session_key or st.session_key or "").strip()
    lines: list[str] = []

    for user, assistant in _load_recent_turns(sk, limit=turn_limit):
        if user:
            lines.append(f"用户：{user}")
        if assistant:
            lines.append(f"你：{assistant}")

    if not lines:
        if st.last_user_message.strip():
            lines.append(f"用户：{_clip(st.last_user_message)}")
        if st.last_assistant_message.strip():
            lines.append(f"你：{_clip(st.last_assistant_message)}")

    if not lines:
        return ""
    return (
        "近期对话（请先读懂以下上下文，再决定说什么）：\n"
        + "\n".join(lines)
    )


def build_silence_scenario_hint(
    bundle: SessionPresenceBundle,
    session_key: str = "",
    *,
    now: datetime | None = None,
) -> str:
    ts = now or datetime.now()
    st = bundle.state
    idle_min = 0
    if st.last_user_activity_at:
        idle_min = max(0, int((ts - st.last_user_activity_at).total_seconds() // 60))

    user_line = _clip(st.last_user_message.strip(), _TURN_CLIP)
    assistant_line = _clip(st.last_assistant_message.strip(), _TURN_CLIP)

    parts: list[str] = [f"用户约 {idle_min} 分钟没有新消息，但仍在同一会话中。"]
    if user_line:
        parts.append(f"用户最后一句话：「{user_line}」。")
    if assistant_line:
        parts.append(f"你最后一句话：「{assistant_line}」。")
    parts.append(
        "请结合以上内容和「近期对话」理解：用户此刻可能在做什么、你们刚聊到什么，"
        "再像真人一样自然续一句或轻声关心。"
    )
    return "当前情境：" + "".join(parts)
