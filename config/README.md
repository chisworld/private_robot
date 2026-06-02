# 配置说明

| 类型 | 位置 | 说明 |
|------|------|------|
| **密钥 / 环境** | 项目根 `.env` | 从 `.env.example` 复制；**API Key 优先写这里** |
| **LLM 业务配置** | `data/config/llm.json` | 模型名、系统提示、角色 ID（勿提交真实 Key） |
| **TTS 业务配置** | `data/config/tts.json` | 引擎路径、参考音频等 |
| **桌宠 UI** | `data/config/pet_ui.json` | 字号、人物缩放等 |
| **角色人设** | `data/config/{角色名}.json` | 各角色 system 设定 |
| **配置模板** | `config/templates/*.example` | 首次部署参考 |

加载顺序（LLM）：`llm.json` → `local_config.py`（可选）→ **`.env` 覆盖密钥与 base_url**
