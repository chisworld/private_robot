# 配置说明

仓库：<https://github.com/chisworld/private_robot>

| 类型 | 位置 | 说明 |
|------|------|------|
| **密钥** | 项目根 `.env` | 从 `.env.example` 复制；**API Key 写这里，勿提交** |
| **LLM** | `data/config/llm.json` | 模型、NSFW、本地 Qwen、active_character |
| **TTS** | `data/config/tts.json` | 引擎、9880、权重路径 |
| **记忆** | `data/config/memory.json` | top_k、提取、衰减、日记；Chroma 由依赖自动启用 |
| **MCP** | `data/config/mcp.json` | Playwright、filesystem 等 |
| **在场感** | `data/config/presence.json` | 空闲搭话、番茄、问候 |
| **桌宠 UI** | `data/config/pet_ui.json` | 字号、缩放、窗口 |
| **系统操控** | `data/config/system_control.json` | 音量、亮度、音乐、关机 |
| **剪贴板** | `data/config/clipboard.json` | 剪贴板总结 |
| **翻译** | `data/config/translate.json` | 百度翻译（气泡中文） |
| **角色人设** | `data/config/{角色名}.json` | 各角色 system 片段 |
| **模板** | `config/templates/*.example` | 首次部署参考 |

本仓库 `data/config/*.json` **已纳入 Git**（私有备份）；克隆到新机器后仍需自行复制 `.env`。

加载顺序（LLM 密钥）：`llm.json` → `local_config.py`（可选）→ **`.env` 覆盖**
