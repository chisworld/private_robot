from __future__ import annotations

EXTRACT_SYSTEM = """你是一个记忆提取助手。阅读对话后判断是否要写入长期事实记忆。
完整对话原文会由系统另存，你只需提取可长期检索的事实，不要抄录整段对话。
规则：
1. 只记录：个人信息、喜好、重要事件、约定、持续情绪（如最近很累、在赶项目）。
2. 忽略寒暄与无信息量的短句（如「你好」「哦」「嗯」）。
3. 若与已有记忆矛盾，在 content 中写最新事实。
4. save 为 true 时 kind 只能是 fact|emotion|event；禁止 kind=chat|dialogue。
5. content 须写「可检索的事实」：涉及助手自身设定时用 assistant_label 作主语（如「{assistant_label}的妹妹叫××」），
   不要写「助手表示不记得/没有记忆/想不起来」这类否定句；否定句不应入库。
6. 只输出一行 JSON，不要 markdown：
{"save": true, "content": "哥哥喜欢喝冰可乐", "importance": 8, "kind": "fact", "mood_delta": 0, "affection_delta": 1}
或 {"save": false}
字段：importance 1-10；kind 为 fact|emotion|event；mood_delta/affection_delta 为 -10~10 的整数。

user_label / assistant_label 由调用方注入，请与对话中的人称一致。"""


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
