"""本地 Qwen3.6 (llama-server) 路径与健康检查。"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from pnn.core.paths import (
    QWEN_LOCAL_BUNDLE_DIR,
    QWEN_LOCAL_DEFAULT_ALIAS,
    QWEN_LOCAL_DEFAULT_PORT,
)

LITE_MAX_TOKENS = 768
LITE_MAX_HISTORY = 2
LITE_MEMORY_CHARS = 0
LITE_ASSISTANT_HISTORY_CHARS = 160
LITE_USER_HISTORY_CHARS = 240


def default_local_model_config() -> dict[str, str]:
    return {
        "local_model_base_url": f"http://127.0.0.1:{QWEN_LOCAL_DEFAULT_PORT}",
        "local_model": QWEN_LOCAL_DEFAULT_ALIAS,
        "local_model_api_key": "local",
    }


def bundle_installed() -> bool:
    return (QWEN_LOCAL_BUNDLE_DIR / "llama-server.exe").is_file()


def local_llm_health(base_url: str) -> tuple[bool, str]:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return False, "未配置本地模型地址"
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=2.5) as resp:
            if resp.status == 200:
                return True, "运行中"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc) or "无响应"
    return False, "无响应"


def local_model_status_text(base_url: str) -> str:
    if not bundle_installed():
        return f"未找到模型目录 {QWEN_LOCAL_BUNDLE_DIR.name}（需 llama-server.exe）"
    ok, detail = local_llm_health(base_url)
    if ok:
        return f"llama-server 已就绪 ({base_url.rstrip('/')})"
    return (
        f"llama-server 未运行 ({detail})。"
        "请重新启动桌宠（会自动后台加载），或查看 data/logs/qwen_boot.log"
    )


def local_chat_lite_enabled(cfg_lite: bool | None = None) -> bool:
    """精简本地上下文：默认开启，显著缩短 prefill。"""
    env = os.getenv("LOCAL_CHAT_LITE", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    if cfg_lite is not None:
        return bool(cfg_lite)
    return True


def local_chat_max_tokens(*, lite: bool = False) -> int:
    if lite:
        raw = os.getenv("LOCAL_CHAT_LITE_MAX_TOKENS", str(LITE_MAX_TOKENS)).strip()
    else:
        raw = os.getenv("LOCAL_CHAT_MAX_TOKENS", "1024").strip()
    try:
        return max(256, int(raw))
    except ValueError:
        return LITE_MAX_TOKENS if lite else 1024


def local_chat_max_history(cfg_max: int, *, lite: bool = False) -> int:
    if lite:
        raw = os.getenv("LOCAL_CHAT_LITE_MAX_HISTORY", str(LITE_MAX_HISTORY)).strip()
        try:
            cap = max(2, int(raw))
        except ValueError:
            cap = LITE_MAX_HISTORY
        return cap
    raw = os.getenv("LOCAL_CHAT_MAX_HISTORY", "8").strip()
    try:
        cap = max(2, int(raw))
    except ValueError:
        cap = 8
    return min(max(2, int(cfg_max or 20)), cap)


def local_memory_max_chars(*, lite: bool = False) -> int:
    if lite:
        return 0
    raw = os.getenv("LOCAL_MEMORY_MAX_CHARS", "900").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 900


def compact_local_chat_grounding_rules() -> str:
    """本地精简模式：防止模型无视用户消息、按人设自说自话。"""
    return (
        "【对话锚定·必须遵守】\n"
        "1. 必须先直接回应用户**上一条消息**的内容；不得无视、偏题或答非所问。\n"
        "2. 不得编造用户未提及的情景、习惯、约定或对话"
        "（例如臆测「哥哥常说…」「这个时间你会…」「周末阳光/空调/下次一定」等）。\n"
        "3. 用户未明确问「几点/现在什么时间」时，禁止主动报时或拿时刻开场。\n"
        "4. 人设仅作口吻参考；话题与事实以用户最新消息为准。"
        "禁止复读 history 里 assistant 已说过的句式、场景、抱怨或长篇独白。\n"
        "5. 只写角色**说出口的台词**；禁止（）内动作/神态/场景描写，"
        "禁止第三人称旁白；肢体表现只用句首【动作:名称】标签。\n"
        "6. 日常闲聊默认 **1～3 句** 短回复；除非用户明确要求长文，"
        "禁止连续多段「」式说教或场景铺陈。"
    )


def compact_local_pet_expression_prompt() -> str:
    """本地精简模式：短标签说明，替代完整表情/动作列表。"""
    return (
        "【句首标签·界面不显示】顺序：【情绪:id】【表情:名】【动作:名】（动作可省略）。\n"
        "情绪 id：soft、high、angry、asking、ironic、normal1、normal2。\n"
        "表情名用 Live2D 英文名（如 default、Black、blush）；禁止【:name】省略写法。\n"
        "正文只能是台词，禁止（）描写与旁白。"
    )


def extract_local_preserved_extra(extra_system: str | None) -> str:
    """从完整 extra 中保留日程/陪伴等短前缀，丢弃冗长表情列表。"""
    raw = (extra_system or "").strip()
    if not raw:
        return ""
    kept: list[str] = []
    for block in raw.split("\n\n"):
        b = block.strip()
        if not b:
            continue
        head = b[:48]
        if (
            b.startswith("[schedule]")
            or b.startswith("[reminder]")
            or b.startswith("[presence]")
            or head.startswith("【在场")
            or head.startswith("【日程")
            or head.startswith("【提醒")
        ):
            kept.append(b)
    return "\n\n".join(kept)


def build_local_lite_extra_system(extra_system: str | None) -> str:
    """本地 lite：保留日程前缀 + 短标签说明（锚定规则见 system messages）。"""
    parts: list[str] = []
    preserved = extract_local_preserved_extra(extra_system)
    if preserved:
        parts.append(preserved)
    parts.append(compact_local_pet_expression_prompt())
    return "\n\n".join(parts)


def local_lite_character_max_chars() -> int:
    raw = os.getenv("LOCAL_LITE_CHARACTER_MAX_CHARS", "600").strip()
    try:
        return max(300, int(raw))
    except ValueError:
        return 600


def local_chat_history_assistant_max_chars() -> int:
    raw = os.getenv("LOCAL_CHAT_LITE_ASSISTANT_HISTORY_CHARS", str(LITE_ASSISTANT_HISTORY_CHARS)).strip()
    try:
        return max(40, int(raw))
    except ValueError:
        return LITE_ASSISTANT_HISTORY_CHARS


def local_chat_history_user_max_chars() -> int:
    raw = os.getenv("LOCAL_CHAT_LITE_USER_HISTORY_CHARS", str(LITE_USER_HISTORY_CHARS)).strip()
    try:
        return max(40, int(raw))
    except ValueError:
        return LITE_USER_HISTORY_CHARS


def _clip_history_content(text: str, cap: int) -> str:
    body = (text or "").strip()
    if not body or len(body) <= cap:
        return body
    return body[:cap].rstrip() + "…"


def trim_history_for_local_llm(
    history: list[dict[str, str]],
    *,
    cap: int,
    lite: bool = True,
) -> list[dict[str, str]]:
    """本地 lite：少轮次 + 截断 assistant 长独白，减轻套话复读。"""
    items = [h for h in (history or []) if (h.get("content") or "").strip()]
    if cap > 0 and len(items) > cap:
        items = items[-cap:]
    if not lite:
        return items
    user_cap = local_chat_history_user_max_chars()
    asst_cap = local_chat_history_assistant_max_chars()
    out: list[dict[str, str]] = []
    for item in items:
        role = (item.get("role") or "").strip()
        content = (item.get("content") or "").strip()
        if not role or not content:
            continue
        if role == "assistant":
            content = _clip_history_content(content, asst_cap)
        elif role == "user":
            content = _clip_history_content(content, user_cap)
        out.append({"role": role, "content": content})
    return out


def build_local_anti_echo_hint(history: list[dict[str, str]]) -> str:
    """若上一条 assistant 较长，提醒勿复读同模板。"""
    last_asst = ""
    for item in reversed(history or []):
        if (item.get("role") or "").strip() == "assistant":
            last_asst = (item.get("content") or "").strip()
            break
    if len(last_asst) < 80:
        return ""
    return (
        "【勿复读】上一条 assistant 回复较长；本轮禁止重复其场景、报时、"
        "周末/阳光/空调/找借口/「下次一定」等套话，换 fresh 角度或直接答用户新问题。"
    )


def estimate_prompt_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)
