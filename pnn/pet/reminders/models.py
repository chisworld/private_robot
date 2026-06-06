from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ReminderStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    missed = "missed"
    cancelled = "cancelled"


class Reminder(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    session_key: str = Field(default="")
    title: str
    description: str = ""
    character_name: str = ""
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    status: ReminderStatus = ReminderStatus.pending
    triggered_at: Optional[datetime] = None
    start_notified_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    source: str = "manual"

    def effective_end(self) -> datetime:
        if self.scheduled_end is not None:
            return self.scheduled_end
        return self.scheduled_start
