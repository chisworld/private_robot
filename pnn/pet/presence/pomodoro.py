"""番茄钟 / 专注陪伴状态（按 session 持久化）。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from pnn.core.paths import DATA_DIR
from pnn.pet.presence.config import load_presence_config

logger = logging.getLogger(__name__)

_POMO_DIR = DATA_DIR / "presence" / "pomodoro"

# 强信号：番茄 / 专注 / 明确计时
_START_STRONG_RE = re.compile(
    r"(?:"
    r"番茄(?:钟|工作法)?|pomodoro|专注模式"
    r"|(?:陪|跟|同)(?:我|咱)?(?:一起|一块|来)?(?:专注|番茄|干活|做事|写(?:代码|作业|稿)?|学习|复习|码字|看书)"
    r"|(?:来|开|整|搞)(?:个|一个)?(?:番茄|pomodoro|专注)"
    r"|(?:开始|启动|进入|切换(?:到)?)(?:一个)?(?:的)?(?:专注|番茄|番茄钟|专注模式)"
    r"|(?:倒计时|计时)(?:一下)?"
    r"|(?:安静|别吵|别打扰|不要打扰)(?:陪|跟)?我"
    r")",
    re.IGNORECASE,
)
# 弱信号：需同时出现时长或陪伴词，避免「我在学习」误触
_START_SOFT_RE = re.compile(
    r"(?:"
    r"我(?:要|想|准备|打算)(?:开始)?(?:专注|番茄|干活|学习|复习|写(?:代码|作业))"
    r"|(?:一起|陪我)(?:写|学|干|做|码)"
    r")",
    re.IGNORECASE,
)
_DURATION_MINUTES_RE = re.compile(r"(\d{1,3})\s*(?:分钟|min|mins|m\b)", re.IGNORECASE)
_DURATION_HOURS_RE = re.compile(r"(\d{1,2})\s*(?:小时|h|hr|hrs)\b", re.IGNORECASE)
_COMPANION_CUE_RE = re.compile(r"陪|跟|一起|一块|安静|别吵|别打扰|番茄|专注|pomodoro", re.IGNORECASE)

_STOP_INTENT_RE = re.compile(
    r"(?:结束|停止|取消|退出|暂停|关掉|关闭|先停|不|别|完了|停了)",
    re.IGNORECASE,
)
_STOP_RE = re.compile(
    r"(?:"
    r"(?:结束|停止|取消|退出|暂停|关掉|关闭|先停)(?:了|一下)?(?:专注|番茄|番茄钟|计时)?"
    r"|(?:不|别)(?:再)?(?:专注|番茄)了"
    r"|(?:先|咱)?(?:不|别)(?:再)?(?:专注|番茄)(?:了)?"
    r"|(?:专注|番茄|番茄钟|计时)(?:已)?(?:结束|完了|停了|先停|取消|结束啦)"
    r"|番茄(?:钟)?(?:先|赶紧)?(?:停|结束|完了|取消)"
    r"|(?:退出|结束|取消)(?:专注|番茄)(?:模式)?"
    r")",
    re.IGNORECASE,
)


class PomodoroPhase(str, Enum):
    idle = "idle"
    focus = "focus"
    break_ = "break"


@dataclass
class PomodoroState:
    phase: str = PomodoroPhase.idle.value
    label: str = "专注"
    work_minutes: int = 25
    break_minutes: int = 5
    started_at: str | None = None
    ends_at: str | None = None
    sessions_today: int = 0
    last_session_date: str = ""

    def is_active(self) -> bool:
        return self.phase in (PomodoroPhase.focus.value, PomodoroPhase.break_.value)

    def remaining_seconds(self, now: datetime | None = None) -> int:
        if not self.ends_at:
            return 0
        ts = now or datetime.now()
        try:
            end = datetime.fromisoformat(self.ends_at)
        except ValueError:
            return 0
        return max(0, int((end - ts).total_seconds()))


@dataclass
class PomodoroEvent:
    kind: str
    label: str = ""
    work_minutes: int = 0
    break_minutes: int = 0


def _safe_name(session_key: str) -> str:
    key = (session_key or "__default__").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _state_path(session_key: str) -> Path:
    return _POMO_DIR / f"{_safe_name(session_key)}.json"


def _extract_duration_minutes(text: str) -> int | None:
    hm = _DURATION_HOURS_RE.search(text)
    if hm:
        try:
            return max(1, min(120, int(hm.group(1)) * 60))
        except ValueError:
            pass
    mm = _DURATION_MINUTES_RE.search(text)
    if mm:
        try:
            return max(1, min(120, int(mm.group(1))))
        except ValueError:
            pass
    return None


def _looks_like_pomodoro_start(text: str) -> bool:
    if _START_STRONG_RE.search(text):
        return True
    if not _START_SOFT_RE.search(text):
        return False
    return bool(
        _extract_duration_minutes(text) is not None
        or _COMPANION_CUE_RE.search(text)
    )


def parse_pomodoro_start_minutes(text: str) -> int | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if not _looks_like_pomodoro_start(raw):
        return None
    explicit = _extract_duration_minutes(raw)
    if explicit is not None:
        return explicit
    cfg = load_presence_config()
    return max(1, min(120, int(cfg.pomodoro_work_minutes or 25)))


def parse_pomodoro_stop(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _looks_like_pomodoro_start(raw) and not _STOP_INTENT_RE.search(raw):
        return False
    return bool(_STOP_RE.search(raw))


class PomodoroService:
    def _load(self, session_key: str) -> PomodoroState:
        path = _state_path(session_key)
        if not path.is_file():
            return PomodoroState()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return PomodoroState()
            st = PomodoroState(**{k: v for k, v in raw.items() if k in PomodoroState.__dataclass_fields__})
            if st.phase not in {p.value for p in PomodoroPhase}:
                st.phase = PomodoroPhase.idle.value
            return st
        except Exception:
            logger.exception("读取番茄钟状态失败: %s", path)
            return PomodoroState()

    def _save(self, session_key: str, state: PomodoroState) -> None:
        path = _state_path(session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")

    def get_state(self, session_key: str) -> PomodoroState:
        return self._load(session_key)

    def is_focusing(self, session_key: str) -> bool:
        st = self._load(session_key)
        return st.phase == PomodoroPhase.focus.value and st.remaining_seconds() > 0

    def start(self, session_key: str, minutes: int | None = None, *, label: str = "专注") -> PomodoroState:
        cfg = load_presence_config()
        work = max(1, min(120, int(minutes or cfg.pomodoro_work_minutes or 25)))
        brk = max(1, min(30, int(cfg.pomodoro_break_minutes or 5)))
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        st = self._load(session_key)
        if st.last_session_date != today:
            st.sessions_today = 0
            st.last_session_date = today
        st.phase = PomodoroPhase.focus.value
        st.label = (label or "专注")[:40]
        st.work_minutes = work
        st.break_minutes = brk
        st.started_at = now.isoformat(timespec="seconds")
        st.ends_at = (now + timedelta(minutes=work)).isoformat(timespec="seconds")
        self._save(session_key, st)
        return st

    def stop(self, session_key: str) -> PomodoroState:
        st = self._load(session_key)
        st.phase = PomodoroPhase.idle.value
        st.started_at = None
        st.ends_at = None
        self._save(session_key, st)
        return st

    def tick(self, session_key: str, *, now: datetime | None = None) -> list[PomodoroEvent]:
        ts = now or datetime.now()
        st = self._load(session_key)
        if st.phase == PomodoroPhase.idle.value or not st.ends_at:
            return []
        if st.remaining_seconds(ts) > 0:
            return []
        events: list[PomodoroEvent] = []
        if st.phase == PomodoroPhase.focus.value:
            st.sessions_today += 1
            st.phase = PomodoroPhase.break_.value
            st.started_at = ts.isoformat(timespec="seconds")
            st.ends_at = (ts + timedelta(minutes=st.break_minutes)).isoformat(timespec="seconds")
            events.append(
                PomodoroEvent(
                    kind="focus_end",
                    label=st.label,
                    work_minutes=st.work_minutes,
                    break_minutes=st.break_minutes,
                )
            )
        elif st.phase == PomodoroPhase.break_.value:
            st.phase = PomodoroPhase.idle.value
            st.started_at = None
            st.ends_at = None
            events.append(
                PomodoroEvent(
                    kind="break_end",
                    label=st.label,
                    work_minutes=st.work_minutes,
                    break_minutes=st.break_minutes,
                )
            )
        self._save(session_key, st)
        return events


_singleton: PomodoroService | None = None


def get_pomodoro_service() -> PomodoroService:
    global _singleton
    if _singleton is None:
        _singleton = PomodoroService()
    return _singleton
