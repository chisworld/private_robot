"""当前激活角色的 AI 回复语言（与 pack.json reply_language 一致）。"""

from __future__ import annotations


def normalize_reply_language(lang: str) -> str:
    code = (lang or "ja").strip().lower()
    if code in ("ja", "jp", "japanese", "日本語", "日语"):
        return "ja"
    if code in ("zh", "cn", "chinese", "中文", "简体中文"):
        return "zh"
    return code


def active_reply_language() -> str:
    try:
        from pnn.characters.pack import load_pack
        from pnn.llm.config_store import load_llm_config

        active = (load_llm_config().active_character or "").strip()
        pack = load_pack(active) if active else None
        return normalize_reply_language(pack.reply_language if pack else "ja")
    except Exception:
        return "ja"


def is_japanese(lang: str | None = None) -> bool:
    return normalize_reply_language(lang or active_reply_language()) == "ja"


def is_chinese(lang: str | None = None) -> bool:
    return normalize_reply_language(lang or active_reply_language()) == "zh"


def agent_summary_instruction(lang: str | None = None) -> str:
    code = normalize_reply_language(lang or active_reply_language())
    if code == "ja":
        return "请用日语（日本語）向用户总结"
    if code == "zh":
        return "请用简体中文向用户总结"
    return "请用角色语言向用户总结"


def agent_download_report_instruction(lang: str | None = None) -> str:
    code = normalize_reply_language(lang or active_reply_language())
    if code == "ja":
        return (
            "向用户用日语报告是否成功、保存的文件名与路径；"
            "说明原文将用于日语语音合成"
        )
    if code == "zh":
        return (
            "向用户用简体中文报告是否成功、保存的文件名与路径；"
            "说明原文将用于中文语音合成"
        )
    return "向用户报告是否成功、保存的文件名"


def screenshot_task_reply_note(lang: str | None = None) -> str:
    code = normalize_reply_language(lang or active_reply_language())
    if code == "ja":
        return (
            "【回复要求】朗读段用日语（将用于日语语音合成）；"
            "须另起一行【中文】写同义简体中文（界面气泡用）。"
        )
    if code == "zh":
        return "【回复要求】请用简体中文向用户汇报结果（将用于中文语音合成）。"
    return ""
