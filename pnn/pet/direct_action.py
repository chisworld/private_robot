"""用户直接口令：说「坐」「点头」等 → 立即执行 Live2D 动作。"""

from __future__ import annotations

import re

from pnn.pet.actions import ACTION_NAMES, resolve_action_name

# 去掉首尾标点后做口令匹配
_STRIP_PUNCT = re.compile(r"^[。！？!?…~～,，、\.]+|[。！？!?…~～,，、\.]+$")
_NEGATION = re.compile(r"(不要|别|不必|不许|不能|无需|未|没)")
_QUESTION = re.compile(r"(吗|么|呢|\?|？|能不能|会不会|可不可以|为什么|怎么|为何|什么)")
# 已知角色名 + 可选「你/请」
_KNOWN_CHARACTER_NAMES = ("里想奈", "理想奈", "塞拉", "树里亚", "14酱")
_NAME_PREFIX = re.compile(
    rf"^(?:{'|'.join(re.escape(n) for n in _KNOWN_CHARACTER_NAMES)})(?:你|请)?"
)
_LEADING_ADDRESS = re.compile(r"^(?:你|请)")

# action_id -> 匹配用户原话的正则（已 normalize + 去称呼）
_COMMAND_PATTERNS: dict[str, re.Pattern[str]] = {
    "sit": re.compile(
        r"^(?:请|给我|来|快|那?(?:你|就)?)?"
        r"(?:坐(?:一下|下|个)?|坐下)"
        r"(?:吧|呀|啊|哦|嘛|了|呗)?$",
    ),
    "nod": re.compile(
        r"^(?:请|给我|来|快|那?(?:你|就)?)?"
        r"(?:点(?:一下|下)?头|点头)"
        r"(?:吧|呀|啊|哦|嘛|了|呗)?$",
    ),
    "shake_head": re.compile(
        r"^(?:请|给我|来|快|那?(?:你|就)?)?"
        r"(?:摇(?:一下|下)?头|摇头)"
        r"(?:吧|呀|啊|哦|嘛|了|呗)?$",
    ),
    "bow": re.compile(
        r"^(?:请|给我|来|快|那?(?:你|就)?)?"
        r"(?:鞠(?:一下|个)?躬|鞠躬|低头)"
        r"(?:吧|呀|啊|哦|嘛|了|呗)?$",
    ),
}

_EXACT_COMMANDS: dict[str, str] = {
    "坐": "sit",
    "坐下": "sit",
    "点头": "nod",
    "摇头": "shake_head",
    "鞠躬": "bow",
}

_ACTION_LABELS: dict[str, str] = {action_id: label for action_id, label in ACTION_NAMES}


def _normalize(text: str) -> str:
    t = (text or "").strip()
    t = _STRIP_PUNCT.sub("", t)
    t = re.sub(r"[,，]", "", t)
    return t.strip()


def _strip_address(text: str) -> str:
    """去掉角色名与「你/请」等称呼，便于匹配「里想奈你跳一下」。"""
    t = _normalize(text)
    t = _NAME_PREFIX.sub("", t, count=1).strip()
    t = _LEADING_ADDRESS.sub("", t, count=1).strip()
    return t


def parse_direct_action_command(text: str) -> str | None:
    """解析用户直接动作口令，返回 ACTIONS 键名；非口令返回 None。"""
    raw = (text or "").strip()
    if not raw or len(raw) > 32:
        return None
    norm = _strip_address(raw)
    if not norm:
        return None
    if _NEGATION.search(norm):
        return None
    if _QUESTION.search(norm) and len(norm) > 4:
        return None

    if norm in _EXACT_COMMANDS:
        return _EXACT_COMMANDS[norm]

    for action_id, pattern in _COMMAND_PATTERNS.items():
        if pattern.match(norm):
            return action_id

    if len(norm) <= 6:
        resolved = resolve_action_name(norm)
        if resolved:
            return resolved

    return None


def direct_action_label(action_id: str) -> str:
    """动作 id 对应的中文说明，供 LLM 前缀使用。"""
    return _ACTION_LABELS.get(action_id, action_id)


def build_direct_action_prompt(action_id: str) -> str:
    label = direct_action_label(action_id)
    return (
        f"[direct_action] 用户口头命令你「{label}」，你已立刻执行该动作。"
        "请用角色口吻极短回应（1 句即可），配合刚做的动作；不要拒绝或长篇解释。"
    )
