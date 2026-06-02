from __future__ import annotations

EXTRACT_SYSTEM = """你是一个记忆提取助手。阅读对话后判断是否要写入主人的长期记忆。
规则：
1. 只记录：个人信息、喜好、重要事件、约定、持续情绪（如最近很累、在赶项目）。
2. 忽略寒暄与无信息量的短句（如「你好」「哦」「嗯」）。
3. 若与已有记忆矛盾（如以前爱喝可乐今天说戒了），在 content 中写最新事实，并设 replace_hint 为旧事实关键词。
4. 只输出一行 JSON，不要 markdown：
{"save": true, "content": "主人喜欢喝冰可乐", "importance": 8, "kind": "fact", "mood_delta": 0, "affection_delta": 1}
或 {"save": false}
字段：importance 1-10；kind 为 fact|emotion|event；mood_delta/affection_delta 为 -10~10 的整数。"""


def extract_user_block(
    user_message: str,
    assistant_reply: str,
    *,
    recent_history: str = "",
) -> str:
    parts = [f"主人：{user_message.strip()}", f"桌宠：{assistant_reply.strip()}"]
    if recent_history.strip():
        parts.insert(0, f"近期上下文：\n{recent_history.strip()}")
    return "\n".join(parts)
