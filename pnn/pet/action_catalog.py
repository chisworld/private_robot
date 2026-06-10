"""为 LLM 生成动作标注提示。"""

from __future__ import annotations

from pnn.pet.actions import ACTION_NAMES


def build_llm_action_instruction() -> str:
    lines = "\n".join(f"- 【动作:{name}】— {desc}" for name, desc in ACTION_NAMES)
    return (
        "【Live2D 动作标注 — 可选，用户界面不会显示这些标签】\n"
        "当该句展示语气适合配合肢体动作时，在【表情:名称】后面紧跟一个动作标签，"
        "格式严格为：【动作:名称】\n"
        "其中「名称」必须从下列列表中逐字复制：\n"
        f"{lines}\n"
        "表情与动作宜一致：开心/兴奋配 sway；害羞/温柔配 tilt_head；"
        "道谢/道歉/问候配 bow；否定/吐槽配 shake_head；惊讶配 surprise；"
        "肯定/同意配 nod；疲惫/休息配 sit 或 stretch；"
        "【情绪:high】宜 sway，【情绪:soft】宜 tilt_head，"
        "【情绪:angry】宜 shake_head，【情绪:asking】宜 tilt_head。\n"
        "动作标签只在需要时使用，并非每句都必须有。\n"
        "标签只出现在句首，正文与朗读内容中不得出现「动作」「【】」等说明字样。"
    )
