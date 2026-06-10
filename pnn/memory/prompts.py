from __future__ import annotations

EXTRACT_SYSTEM = """你是一个记忆提取助手。阅读对话后判断是否要写入长期事实记忆。
完整对话原文会由系统另存，你只需提取可长期检索的事实，不要抄录整段对话。

【应记录的内容（尽量全面，每条独立成句）】
■ 身份与关系：姓名、昵称、称呼偏好、家人、伴侣、宠物、同事、老师、职业、学校、班级、居住地、老家。
■ 喜好与习惯：饮食偏好/禁忌/过敏、作息、熬夜、常玩游戏/追的剧/听的歌、穿衣风格、常用语气。
■ 健康与状态：过敏、慢性病、受伤、感冒、发烧、疲劳、压力、心情持续低落/兴奋（kind=emotion）。
■ 重要经历：旅行、搬家、换工作、考试、面试、获奖、吵架和好、分手复合（kind=event）。
■ 游戏/赌约结果：胜负、约定与兑现（如「osu 赌局哥哥赢了并兑现约定」），kind=event。
■ 持续事实：在做的项目、在学的课、长期目标、固定爱好、常去地点。
■ 角色设定：用户透露的、关于助手/角色自身的关系或设定（用 assistant_label 作主语，如「{assistant_label}的妹妹叫××」）。

【时间约定 / 待办 — 与记忆的分工】
程序会从**用户原话**自动解析并写入待办，下列类型**不要**再当 fact/event 重复存：
- 具体时刻：「11点睡觉」「22:30吃药」「下午三点开会」「六点半叫我」
- 相对时间：「三分钟后喝水」「半小时后叫我」「过会儿提醒收菜」「待会一起洗澡」
- 日期：「明天吃饭」「后天体检」「周末爬山」「下周三分组讨论」「今晚追剧」
- 提醒口令：「别忘了」「记得叫我」「到时候提醒」「设个闹钟」
- 共同计划：「我们11点睡吧」「一起走」「一起去」「约好了」

但若同一句里还有**长期信息**，只提取长期部分，例如：
- 「以后都11点睡，你别熬夜」→ save=true，content 写作息习惯，不要只写「11点睡觉」
- 「鸣潮活动要每天做，九点提醒我」→ 待办由程序建；记忆可写「哥哥常玩鸣潮/做鸣潮日常」
- 「我不能吃辣，明天中午别点辣的」→ 记忆写「哥哥不能吃辣」

【不应记录】
寒暄（你好/嗯/哦）；纯日程重复；助手「不记得/想不起来」类否定句；已有记忆的换说法重复。

【规则】
1. 与已有记忆矛盾 → content 写最新事实。
2. save=true 时 kind 仅 fact|emotion|event；禁止 chat|dialogue。
3. content 须可检索；涉及助手用 assistant_label。
4. 「今天/昨天」须与用户块「当前时间」一致。
5. 用户未在本轮再次确认的旧事，助手仅提醒 → save=false。
6. 只输出一行 JSON，无 markdown：
{"save": true, "content": "…", "importance": 8, "kind": "fact", "mood_delta": 0, "affection_delta": 1}
或 {"save": false}

user_label / assistant_label 由调用方注入。"""


def extract_user_block(
    user_message: str,
    assistant_reply: str,
    *,
    recent_history: str = "",
    related_memories: str = "",
    now_text: str = "",
    user_label: str = "主人",
    assistant_label: str = "助手",
) -> str:
    parts: list[str] = []
    if now_text.strip():
        parts.append(f"当前时间：{now_text.strip()}")
    if related_memories.strip():
        parts.append(f"已有相关记忆（勿重复入库）：\n{related_memories.strip()}")
    if recent_history.strip():
        parts.append(f"近期上下文：\n{recent_history.strip()}")
    parts.append(f"{user_label}：{user_message.strip()}")
    parts.append(f"{assistant_label}：{assistant_reply.strip()}")
    return "\n".join(parts)
