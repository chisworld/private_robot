# PNN Garden

仓库：<https://github.com/chisworld/Pnn_garden>

本地 AI Agent 平台：语音识别、语音合成、大语言模型、MCP 工具调用，通过对话让 AI 帮你做事。

## 项目结构

详见 [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md)。

```
pnn_garden/
├── .env.example          # 复制为 .env，填入 API Key 等密钥
├── apps/web/             # Next.js 前端
├── server/               # FastAPI 网关 (8765)
├── pnn/                  # ASR / TTS / LLM / pet 桌宠
├── cli/                  # 命令行工具
├── scripts/              # launcher、run_pet 等
├── data/config/          # 业务配置 JSON（不含密钥）
├── config/templates/     # 配置模板
├── live2d/14酱/          # Live2D 模型
├── docs/                 # 文档与 UI 设计规范
├── launch/               # 启动脚本
├── 一键启动.bat          # API + 网页
└── 启动桌宠.bat          # 原生桌宠
```

## 环境变量（.env）

```powershell
copy .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY=sk-...
```

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | LLM API 密钥（优先于 llm.json） |
| `DEEPSEEK_BASE_URL` | API 地址，默认 DeepSeek |
| `PNN_API_PORT` | 本地网关端口，默认 8765 |
| `TTS_SERVER_URL` | GPT-SoVITS 地址，默认 9880 |
| `TTS_API_KEY` | 云 TTS 密钥（可选） |

## 快速开始（一键启动）

**双击项目根目录的 `一键启动.bat`**（或 `start.bat`）。

启动器会自动完成：

1. 检查 Python / Node.js
2. 首次运行时安装 `requirements.txt` 与 `apps/web` 的 npm 依赖
3. 拉起 **API**（`127.0.0.1:8765`）与 **网页**（`localhost:3000`）
4. 尝试后台启动 TTS（若已配置 GPT-SoVITS）
5. 打开浏览器 **语音对话页** `http://localhost:3000/chat`

无需再单独执行 `python -m server.main` 或手动 `npm run dev`。

命令行等价：

```powershell
python scripts/launcher.py              # 默认打开 /chat
python scripts/launcher.py --page asr   # 打开语音识别
python scripts/launcher.py --no-browser # 不自动开浏览器
```

安装过 editable 包后也可：`pnn-garden`

## 单独运行

```powershell
# 仅 API
python -m server.main

# ASR 命令行
python cli/asr.py --stream --language zh
```

## 模型路径

Whisper（ASR）与 GPT-SoVITS（TTS）模型放在项目根 `models/`：

```
models/ASR/whisper/faster_whisper_tiny/
models/ASR/whisper/faster_whisper_small/
models/TTS/GPT-SoVITS-v2pro-20250604/
```

Live2D 桌宠模型：`live2d/14酱/`（旧路径 `assets/live2d`、`launch/assets/live2d` 仍会自动兼容）。

## 后续扩展

| 模块 | 目录 | 说明 |
|------|------|------|
| TTS | `pnn/tts/` | 语音合成，Agent 回复朗读 |
| LLM | `pnn/llm/` | 对话大模型 |
| Agent | `pnn/agent/` | 串联 ASR→LLM→TTS→MCP |
| MCP | `pnn/mcp/` | 外部工具协议 |
| 路由 | `server/routes/` | 新增 `tts.py` / `chat.py` / `mcp.py` |
| 前端 | `apps/web/src/features/` | 新增 `chat/`、`tts/` 等 |
