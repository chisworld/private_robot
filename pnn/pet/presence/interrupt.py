"""连发消息检测（轻量抢话）。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


class InterruptTracker:
    def __init__(
        self,
        *,
        window_seconds: float = 10.0,
        threshold: int = 3,
        cooldown_seconds: float = 45.0,
    ) -> None:
        self._window = max(1.0, float(window_seconds))
        self._threshold = max(2, int(threshold))
        self._cooldown = max(5.0, float(cooldown_seconds))
        self._times: deque[datetime] = deque()
        self._last_interrupt_at: datetime | None = None

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._window)
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def record_and_should_interrupt(self, now: datetime | None = None) -> bool:
        ts = now or datetime.now()
        self._prune(ts)
        self._times.append(ts)
        if len(self._times) < self._threshold:
            return False
        if self._last_interrupt_at and (ts - self._last_interrupt_at).total_seconds() < self._cooldown:
            return False
        self._last_interrupt_at = ts
        self._times.clear()
        return True
