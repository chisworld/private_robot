from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EmotionMood(str, Enum):
    neutral = "neutral"
    happy = "happy"
    annoyed = "annoyed"
    sad = "sad"
    worried = "worried"
    sleepy = "sleepy"


class TimelineEventType(str, Enum):
    appointment = "appointment"
    fulfillment = "fulfillment"
    absence = "absence"
    emotion = "emotion"
    focus = "focus"
    idle = "idle"
    profile = "profile"


class UserLifeProfile(BaseModel):
    preferred_name: str = ""
    taboos: list[str] = Field(default_factory=list)
    preferences: dict[str, str] = Field(default_factory=dict)
    char_catchphrases: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.now)


class TimelineEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: TimelineEventType
    summary: str
    occurred_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionPresenceState(BaseModel):
    session_key: str = ""
    character_name: str = ""
    last_user_activity_at: datetime | None = None
    last_window_focus_at: datetime | None = None
    last_window_blur_at: datetime | None = None
    last_session_seen_at: datetime | None = None
    window_focused: bool = True
    emotion_mood: EmotionMood = EmotionMood.neutral
    emotion_reason: str = ""
    trust_level: int = Field(default=50, ge=0, le=100)
    unread_proactive_count: int = Field(default=0, ge=0)
    last_proactive_at: datetime | None = None
    idle_nudge_count: int = Field(default=0, ge=0)
    last_interrupt_at: datetime | None = None
    last_time_greeting_key: str = ""
    last_holiday_greeting_key: str = ""
    last_user_message: str = ""
    last_assistant_message: str = ""


class SessionPresenceBundle(BaseModel):
    state: SessionPresenceState = Field(default_factory=SessionPresenceState)
    profile: UserLifeProfile = Field(default_factory=UserLifeProfile)
    timeline: list[TimelineEvent] = Field(default_factory=list)
