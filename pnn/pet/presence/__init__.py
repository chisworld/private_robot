"""桌宠在场感：空闲搭话、窗口焦点、情绪持久化、生活上下文等。"""

from pnn.pet.presence.config import PresenceConfig, load_presence_config, save_presence_config
from pnn.pet.presence.runtime import PresenceRuntime
from pnn.pet.presence.service import get_presence_service

__all__ = [
    "PresenceConfig",
    "PresenceRuntime",
    "get_presence_service",
    "load_presence_config",
    "save_presence_config",
]
