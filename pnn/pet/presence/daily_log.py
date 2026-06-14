"""当日对话短摘要（按 session + 日期）。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from pnn.core.paths import DATA_DIR

logger = logging.getLogger(__name__)

_LOG_DIR = DATA_DIR / "presence" / "daily_log"
_MAX_TURNS = 40
_SNIP = 120

_SUMMARY_QUERY_RE = re.compile(
    r"(?:"
    r"今天(?:我们|咱俩|你和我)?(?:聊|说|讨论|讲|谈|交流|对话)了?(?:什么|啥|哪些|些什么)"
    r"|今天(?:都|有)?(?:聊|说|讲)了(?:什么|啥|哪些|些什么)"
    r"|今天(?:的)?(?:聊天|对话|谈话|交流)(?:记录|内容|摘要|总结|回顾)?"
    r"|(?:回顾|总结|汇总|整理|回忆)(?:一下)?今天(?:聊|说|讲|的)?(?:的)?(?:内容|对话|聊天)?"
    r"|(?:刚才|之前|早些时候|今儿)(?:我们)?(?:聊|说|讲)了?(?:什么|啥|哪些)"
    r"|还记得今天(?:聊|说|讲)的(?:吗|么|什么|啥)"
    r"|帮我(?:回忆|回想|回顾)(?:一下)?今天"
    r"|今日(?:聊天|对话)?(?:摘要|总结|回顾|记录)"
    r"|今天(?:都|有)哪些(?:话题|内容)"
    r")",
    re.IGNORECASE,
)


@dataclass
class DailyTurn:
    at: str
    user: str
    assistant: str


def is_daily_summary_query(text: str) -> bool:
    return bool(_SUMMARY_QUERY_RE.search((text or "").strip()))


def _safe_name(session_key: str) -> str:
    key = (session_key or "__default__").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _log_path(session_key: str, day: date | None = None) -> Path:
    d = day or date.today()
    return _LOG_DIR / f"{_safe_name(session_key)}_{d.isoformat()}.json"


def _clip(text: str, limit: int = _SNIP) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def append_daily_turn(session_key: str, user_text: str, assistant_text: str) -> None:
    user = _clip(user_text, 80)
    try:
        from pnn.translate.service import translate_service

        assistant_text = translate_service.for_memory_storage(assistant_text)
    except Exception:
        pass
    assistant = _clip(assistant_text, _SNIP)
    if not user and not assistant:
        return
    path = _log_path(session_key)
    turns: list[dict] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                turns = raw
        except Exception:
            logger.warning("daily_log 损坏，将重建: %s", path)
    turns.append(
        asdict(
            DailyTurn(
                at=datetime.now().isoformat(timespec="seconds"),
                user=user,
                assistant=assistant,
            )
        )
    )
    turns = turns[-_MAX_TURNS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")


def build_daily_summary_text(session_key: str, *, day: date | None = None, max_items: int = 12) -> str:
    path = _log_path(session_key, day)
    if not path.is_file():
        return "今天还没有记录到对话摘要。"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取 daily_log 失败")
        return "今天还没有记录到对话摘要。"
    if not isinstance(raw, list) or not raw:
        return "今天还没有记录到对话摘要。"
    lines: list[str] = []
    for item in raw[-max_items:]:
        if not isinstance(item, dict):
            continue
        u = _clip(str(item.get("user") or ""), 60)
        a = _clip(str(item.get("assistant") or ""), 80)
        if not u and not a:
            continue
        at = str(item.get("at") or "")
        hh = at[11:16] if len(at) >= 16 else ""
        prefix = f"{hh} " if hh else ""
        if u and a:
            lines.append(f"- {prefix}用户：{u} → 你：{a}")
        elif u:
            lines.append(f"- {prefix}用户：{u}")
        else:
            lines.append(f"- {prefix}你：{a}")
    if not lines:
        return "今天还没有记录到对话摘要。"
    return "今天聊过的要点（供你回忆，勿逐条复读）：\n" + "\n".join(lines)
