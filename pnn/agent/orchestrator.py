"""Agent 主循环：LLM ↔ MCP 工具调用。"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from pnn.agent.code_edit import (
    boost_max_tokens,
    boost_tool_result_cap,
    build_agent_code_edit_instructions,
    code_edit_temperature,
    looks_like_code_edit_task,
)
from pnn.agent.routing import build_web_search_agent_mandate, looks_like_web_browse_task
from pnn.agent.screenshot_download import build_screenshot_download_agent_section, is_screenshot_download_task
from pnn.launch_apps.direct import try_direct_launch_app
from pnn.system_control.direct import try_direct_system_control
from pnn.system_control.routing import build_system_control_agent_mandate
from pnn.characters.reply_lang import (
    active_reply_language,
    agent_download_report_instruction,
    agent_summary_instruction,
)
from pnn.llm.client import DeepSeekClient
from pnn.mcp.config_store import DEFAULT_MAX_AGENT_STEPS, MAX_AGENT_STEPS_LIMIT, load_mcp_config
from pnn.mcp.service import mcp_service
from pnn.mcp.storage import build_agent_storage_instructions

logger = logging.getLogger(__name__)


def build_launch_apps_agent_section() -> str:
    from pnn.launch_apps.service import launch_apps_service

    launch_apps_service.reload_config()
    hints = launch_apps_service.registered_app_hints()
    if not hints:
        return ""
    joined = "、".join(hints)
    return (
        "【启动程序】当用户语义上想打开本机已登记软件时，必须调用 local__launch_app。\n"
        f"可用 id/别名：{joined}\n"
        "参数 app 填与用户说法最匹配的一项；成功后用角色语气简短确认，"
        "失败或未登记则如实说明，禁止编造已打开。"
    )


def build_system_control_agent_section() -> str:
    from pnn.system_control.service import system_control_service

    if not system_control_service.chat_enabled():
        return ""
    return (
        "【系统操控】当用户语义上想调节音量/亮度、清理回收站、定时关机等时，"
        "必须调用 local__set_volume / local__set_brightness / "
        "local__empty_recycle_bin / local__schedule_shutdown / local__cancel_shutdown；"
        "不必等用户说固定关键词（如「屏幕太刺眼了」也应理解为调暗）。\n"
        "亮度：相对调节用 delta（如「调高8」→ delta=8）；绝对值用 percent（如「调到80%」→ percent=80）。\n"
        "音量：相对调节用 delta（如「调小10」→ delta=-10）；绝对值用 percent。\n"
        "纯闲聊、情感倾诉时不要调用上述工具。\n"
        "完成后用角色语气简短确认；失败则说明原因。关机类操作需确认分钟数符合用户原话。"
    )


def build_clipboard_agent_section() -> str:
    from pnn.clipboard.service import clipboard_service

    if not clipboard_service.chat_enabled():
        return ""
    return (
        "【剪贴板】当用户语义上想总结/翻译/处理刚复制的内容时，"
        "必须先调用 local__read_clipboard_text，再根据返回文本用角色语气摘要或处理；"
        "不必等用户说「剪贴板」等固定词；不要编造剪贴板内容。"
    )


def build_agent_system_prompt(
    reply_language: str | None = None,
    *,
    include_project_map: bool = True,
    include_code_edit: bool = True,
    include_screenshot: bool = False,
    include_web_tools: bool = False,
    include_launch_apps: bool = False,
    include_system_control: bool = False,
    include_clipboard: bool = False,
) -> str:
    """按任务类型注入 Agent 系统提示，避免闲聊时误导模型去开浏览器。"""
    summary = agent_summary_instruction(reply_language)
    report = agent_download_report_instruction(reply_language)
    parts = [
        "【MCP 工具】工具名格式为 server_id__tool_name"
        "（如 playwright__browser_navigate、filesystem__read_text_file）。\n",
    ]
    if include_web_tools or include_screenshot:
        parts.append(
            "★ 用户已要求查网页/搜索：必须先调用 Playwright 完成后再文字回复；"
            "角色扮演不得作为拒绝执行搜索的理由。\n"
            f"查实时网页、自动化浏览器时使用 Playwright；{summary}，不要只贴原始 JSON。\n"
        )
    elif include_launch_apps or include_system_control or include_clipboard:
        parts.append(
            "★ 纯闲聊、情感陪伴、一般知识问答：直接用文字回复，不要调用工具。\n"
            "★ 但当用户语义上需要本机助手（调音量/亮度、回收站、定时关机、"
            "打开已登记程序、处理刚复制内容等）时，必须调用对应 local__ 工具；"
            "由你理解意图，不要等固定关键词，也不要假装已执行。\n"
            "★ 不要主动打开网站、不要搜索网页，除非用户明确提出了相关任务。\n"
        )
    else:
        parts.append(
            "★ 日常闲聊、情感陪伴、角色扮演、一般知识问答：**禁止调用任何工具**，直接用文字回复。\n"
            "★ 不要主动打开网站、不要搜索网页，除非用户明确提出了相关任务。\n"
        )
    if include_code_edit:
        parts.append(build_agent_code_edit_instructions(include_map=include_project_map))
        parts.append("")
    if include_screenshot or include_web_tools:
        parts.append(build_agent_storage_instructions())
    if include_screenshot:
        parts.append("")
        parts.append(build_screenshot_download_agent_section(report))
    launch_section = build_launch_apps_agent_section() if include_launch_apps else ""
    if launch_section:
        parts.append("")
        parts.append(launch_section)
    sys_section = build_system_control_agent_section() if include_system_control else ""
    if sys_section:
        parts.append("")
        parts.append(sys_section)
    clip_section = build_clipboard_agent_section() if include_clipboard else ""
    if clip_section:
        parts.append("")
        parts.append(clip_section)
    if include_code_edit or include_web_tools:
        from pnn.agent.skill_loader import load_companion_skill_text

        companion = load_companion_skill_text()
        if companion:
            parts.append("")
            parts.append(companion)
    return "\n".join(p for p in parts if p.strip())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…(结果已截断)"


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if (msg.get("role") or "").strip() == "user":
            return str(msg.get("content") or "").strip()
    return ""


class AgentOrchestrator:
    """同步 Agent：多轮 tool call 直到模型给出最终文本。"""

    def iter_turn(
        self,
        messages: list[dict[str, Any]],
        client: DeepSeekClient,
        *,
        temperature: float,
        max_tokens: int,
        thinking_enabled: bool = False,
        reasoning_effort: str = "high",
    ) -> Iterator[tuple[str, str]]:
        """产出 ('status', 文案) 或 ('delta', 文本块)。"""
        cfg = load_mcp_config()
        work = list(messages)
        user_text = _last_user_text(work)
        mcp_service.reset_agent_context()
        if is_screenshot_download_task(user_text):
            mcp_service.set_single_image_download(True)
        tools = mcp_service.tools_for_openai(connect=True)
        if not tools:
            raise RuntimeError("无可用工具（请在设置中配置 MCP 或快捷启动）")

        code_task = looks_like_code_edit_task(user_text)
        screenshot_task = is_screenshot_download_task(user_text)
        web_task = looks_like_web_browse_task(user_text)
        from pnn.clipboard.service import clipboard_service
        from pnn.launch_apps.service import launch_apps_service
        from pnn.system_control.service import system_control_service

        launch_task = launch_apps_service.chat_enabled()
        system_task = system_control_service.chat_enabled()
        clipboard_task = clipboard_service.chat_enabled()
        local_only = (
            (launch_task or system_task or clipboard_task)
            and not web_task
            and not screenshot_task
            and not code_task
        )

        # 纯改代码任务：不暴露 Playwright，避免模型顺手去开浏览器
        if code_task and not web_task and not screenshot_task and not launch_task:
            tools = [
                t
                for t in tools
                if not str((t.get("function") or {}).get("name") or "").startswith("playwright__")
            ]
            if not tools:
                raise RuntimeError("无可用 MCP 工具（filesystem）")

        if local_only:
            launch_tools = [
                t
                for t in tools
                if str((t.get("function") or {}).get("name") or "").startswith("local__")
            ]
            if launch_tools:
                tools = launch_tools

        if code_task:
            temperature = code_edit_temperature(temperature)
            max_tokens = boost_max_tokens(max_tokens)

        agent_system = build_agent_system_prompt(
            active_reply_language(),
            include_project_map=code_task,
            include_code_edit=code_task,
            include_screenshot=screenshot_task,
            include_web_tools=web_task or screenshot_task,
            include_launch_apps=launch_task,
            include_system_control=system_task,
            include_clipboard=clipboard_task,
        )
        if not any(m.get("role") == "system" and "MCP 工具" in str(m.get("content", "")) for m in work):
            work.insert(min(1, len(work)), {"role": "system", "content": agent_system})
        if web_task:
            mandate = build_web_search_agent_mandate(user_text)
            if mandate:
                work.insert(min(2, len(work)), {"role": "system", "content": mandate})
        if launch_task:
            direct_launch = try_direct_launch_app(user_text)
            if direct_launch:
                work.insert(
                    min(2, len(work)),
                    {
                        "role": "system",
                        "content": (
                            f"【快捷启动·已由本机执行成功】{direct_launch}\n"
                            "请用角色语气向用户简短确认已打开；禁止再说未登记、"
                            "禁止让用户手动打开、不要重复调用 launch_app。"
                        ),
                    },
                )
        if system_task:
            direct_result = try_direct_system_control(user_text)
            if direct_result:
                work.insert(
                    min(2, len(work)),
                    {
                        "role": "system",
                        "content": (
                            f"【系统操控·已由本机执行成功】{direct_result}\n"
                            "请用角色语气向用户简短确认已完成；禁止再说失败、"
                            "禁止让用户手动调节、不要重复调用同一音量/亮度工具。"
                        ),
                    },
                )
            else:
                sys_mandate = build_system_control_agent_mandate(user_text)
                if sys_mandate:
                    work.insert(min(2, len(work)), {"role": "system", "content": sys_mandate})
                else:
                    work.insert(
                        min(2, len(work)),
                        {
                            "role": "system",
                            "content": (
                                "【系统操控·语义理解】若用户是在抱怨或请求本机环境"
                                "（太亮/太暗/太吵/想关机/清回收站等），请调用相应 local__ 工具；"
                                "若只是聊天则不要调用。"
                            ),
                        },
                    )

        max_steps = max(1, int(cfg.max_agent_steps or DEFAULT_MAX_AGENT_STEPS))
        result_cap = boost_tool_result_cap(cfg.tool_result_max_chars or 12000) if code_task else max(
            500, int(cfg.tool_result_max_chars or 12000)
        )

        for step in range(max_steps):
            yield ("status", f"思考中…（第 {step + 1} 轮）")
            resp = client.chat_completion(
                work,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_enabled=thinking_enabled,
                reasoning_effort=reasoning_effort,
            )
            req_model = client.model
            resp_model = resp.get("model") or req_model
            if resp_model != req_model:
                logger.info(
                    "Agent API 返回模型名: %s（请求 %s）",
                    resp_model,
                    req_model,
                )
            message = resp.get("message") or {}
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
                content = message.get("content")
                if content:
                    assistant_msg["content"] = content
                work.append(assistant_msg)

                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    llm_name = str(fn.get("name") or "").strip()
                    args = _parse_tool_arguments(fn.get("arguments"))
                    tc_id = str(tc.get("id") or llm_name or "tool")
                    yield ("status", f"正在调用工具 {llm_name}…")
                    try:
                        out = mcp_service.call_tool_by_llm_name(llm_name, args)
                        text = _truncate(str(out.get("result") or ""), result_cap)
                    except Exception as exc:
                        logger.warning("MCP 工具 %s 失败: %s", llm_name, exc)
                        text = f"工具调用失败: {exc}"
                    work.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": text,
                        }
                    )
                continue

            final = (message.get("content") or "").strip()
            if not final:
                raise RuntimeError("模型未返回文本（且无 tool_calls）")
            # 模拟流式，便于桌宠气泡逐字刷新
            chunk = 6
            for i in range(0, len(final), chunk):
                yield ("delta", final[i : i + chunk])
            return

        raise RuntimeError(f"Agent 超过最大步数 ({max_steps})，请简化问题后重试")
