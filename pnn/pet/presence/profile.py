"""用户生活档案提取。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from pnn.pet.presence.models import TimelineEventType, UserLifeProfile

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(
    r"(?:叫我|称呼我|你可以叫我|我的名字是)[「\"']?([^「\"'\s，。!！?？]{1,8})"
)
_TABOO_RE = re.compile(r"(?:不要|别|不许|讨厌).{0,6}(叫我|提|说|聊)(.{0,12})")
_PREF_RE = re.compile(r"(?:我喜欢|我爱吃|我习惯|我通常)(.{1,16})")
_CATCHPHRASE_RE = re.compile(r"(?:口癖|常说|习惯说)[「\"']?([^「\"'\n]{2,12})")


def _merge_unique(existing: list[str], new: list[str], limit: int = 12) -> list[str]:
    out = list(existing)
    for item in new:
        t = (item or "").strip()
        if t and t not in out:
            out.append(t)
    return out[-limit:]


def extract_profile_updates(user_text: str, assistant_text: str) -> dict[str, Any]:
    combined = f"{user_text}\n{assistant_text}"
    updates: dict[str, Any] = {}

    m = _NAME_RE.search(combined)
    if m:
        updates["preferred_name"] = m.group(1).strip()

    taboos = [m.group(1).strip() for m in _TABOO_RE.finditer(combined)]
    if taboos:
        updates["taboos"] = taboos

    prefs: dict[str, str] = {}
    for m in _PREF_RE.finditer(combined):
        val = m.group(1).strip()
        if val:
            prefs[f"偏好{len(prefs)+1}"] = val
    if prefs:
        updates["preferences"] = prefs

    catch = [m.group(1).strip() for m in _CATCHPHRASE_RE.finditer(assistant_text)]
    if catch:
        updates["char_catchphrases"] = catch

    return updates


def merge_profile(profile: UserLifeProfile, updates: dict[str, Any]) -> bool:
    changed = False
    if name := updates.get("preferred_name"):
        if name != profile.preferred_name:
            profile.preferred_name = name
            changed = True
    if taboos := updates.get("taboos"):
        merged = _merge_unique(profile.taboos, taboos)
        if merged != profile.taboos:
            profile.taboos = merged
            changed = True
    if prefs := updates.get("preferences"):
        profile.preferences.update(prefs)
        changed = True
    if cp := updates.get("char_catchphrases"):
        merged = _merge_unique(profile.char_catchphrases, cp)
        if merged != profile.char_catchphrases:
            profile.char_catchphrases = merged
            changed = True
    return changed


def sync_profile_from_turn(
    service: Any,
    *,
    user_text: str,
    assistant_text: str,
    character_name: str = "",
) -> bool:
    updates = extract_profile_updates(user_text, assistant_text)
    if not updates:
        return False
    bundle = service.bundle
    if merge_profile(bundle.profile, updates):
        bundle.profile.updated_at = datetime.now()
        if character_name:
            service.set_character_name(character_name)
        service.add_timeline(TimelineEventType.profile, "更新了用户生活档案")
        service.save()
        return True
    return False
