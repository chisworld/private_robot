from __future__ import annotations

EXTRACT_SYSTEM = """你是一个记忆提取助手。阅读对话后判断是否要写入主人的长期事实记忆，并生成本轮对话摘要。
规则：
1. 只记录：个人信息、喜好、重要事件、约定、持续情绪（如最近很累、在赶项目）。
2. 忽略寒暄与无信息量的短句（如「你好」「哦」「嗯」）。
3. 若与已有记忆矛盾，在 content 中写最新事实。
4. chat_summary 必填：一句中文概括本轮（主人做了什么、助手如何回应）；不要写表情名、【表情:…】或「以×表情」。
5. save 为 true 时 kind 只能是 fact|emotion|event；禁止 kind=chat，禁止 content 写【对话记录】或逐字抄录对话原文。
6. 只输出一行 JSON，不要 markdown：
{"save": true, "content": "主人喜欢喝冰可乐", "importance": 8, "kind": "fact", "mood_delta": 0, "affection_delta": 1, "chat_summary": "主人测试效果时，我妻树里亚表示愿意为主人解答任何问题。"}
或 {"save": false, "chat_summary": "主人打招呼，树里亚礼貌回应。"}
字段：importance 1-10；kind 为 fact|emotion|event；mood_delta/affection_delta 为 -10~10 的整数。

assistant_label 由调用方注入，用于 chat_summary 与示例中的人称。"""


def extract_user_block(
    user_message: str,
    assistant_reply: str,
    *,
    recent_history: str = "",
    user_label: str = "主人",
    assistant_label: str = "助手",
) -> str:
    parts = [
        f"{user_label}：{user_message.strip()}",
        f"{assistant_label}：{assistant_reply.strip()}",
    ]
    if recent_history.strip():
        parts.insert(0, f"近期上下文：\n{recent_history.strip()}")
    return "\n".join(parts)
