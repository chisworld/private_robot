# PNN Garden

仓库：<https://github.com/chisworld/Pnn_garden>

本地 AI Agent 平台（v0.2.0）：**语音识别 · 语音合成 · LLM 对话 · MCP 工具 · Live2D 桌宠**，全部在本地运行，通过对话让 AI 帮你做事。

## 功能概览

| 模块 | 说明 |
|------|------|
| **ASR** | faster-whisper 实时/文件语音识别，Web 页与 CLI 均可用 |
| **TTS** | GPT-SoVITS（默认）、Genie TTS、Index TTS、CosyVoice 云；分句朗读、口型同步 |
| **LLM** | DeepSeek / OpenAI 兼容 API，SSE 流式对话，可选思考模式 |
| **Agent + MCP** | 网页搜索、项目内改代码、截图任务等多步工具调用 |
| **视觉识图** | 粘贴/上传截图，经 DashScope VL（Qwen-VL）识别 |
| **角色包** | 多角色人设、Live2D、TTS 音色一键切换 |
| **长期记忆** | RAG 检索、自动提取、日记、衰减与合并 |
| **在场感 / 提醒** | 空闲主动搭话、日程提取与到期提醒（桌宠） |
| **Web 前端** | Next.js 深色 UI：ASR / 语音对话 / TTS 调试 |
| **Live2D 桌宠** | 原生 PySide6 三窗口桌宠，或 WebEngine 嵌入模式 |

## 环境要求

- **Python 3.11+**
- **Node.js 18+**（仅 Web 模式需要）
- **Windows**（批处理启动脚本；Linux/macOS 可用命令行等价方式）
- 至少填写 `.env` 中的 `DEEPSEEK_API_KEY`
- TTS 需本地 [GPT-SoVITS 整合包](docs/TTS_LOCAL_ASSETS.md)（可选，无 TTS 时仍可文字对话）
- 桌宠需 PySide6、live2d-py（见 `requirements.txt`）

## 快速开始

### 1. 克隆与依赖

```powershell
git clone https://github.com/chisworld/Pnn_garden.git
cd Pnn_garden

# 创建虚拟环境（推荐）
python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt
pip install -e .   # 可选：安装 pnn-garden / pnn-asr / pnn-tts 命令
```

### 2. 配置密钥

```powershell
copy .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY=sk-...
```

### 3. 一键启动（推荐）

**双击项目根目录的 `一键启动.bat`**，或在命令行：

```powershell
python scripts/launcher.py              # 默认打开语音对话页 /chat
python scripts/launcher.py --page asr   # 打开语音识别页
python scripts/launcher.py --page tts   # 打开 TTS 调试页
python scripts/launcher.py --no-browser # 不自动开浏览器
```

安装 editable 包后也可直接运行：`pnn-garden`

启动器会自动：

1. 检查 Python / Node.js
2. 首次运行时安装 `requirements.txt` 与 `apps/web` 的 npm 依赖
3. 拉起 **API**（`127.0.0.1:8765`）与 **网页**（`localhost:3000`）
4. 尝试后台启动 TTS（若已配置 GPT-SoVITS）
5. 打开浏览器 **语音对话页** `http://localhost:3000/chat`

## 使用方式

### Web 页面

| 地址 | 功能 |
|------|------|
| `http://localhost:3000/` | **语音转文字**：实时麦克风流式识别、音频文件上传转写 |
| `http://localhost:3000/chat` | **语音对话**（默认）：SSE 流式 LLM、ASR 输入、TTS 朗读、Live2D 口型/表情、设置面板 |
| `http://localhost:3000/tts` | **文字转语音**：引擎配置、参考音、情绪预设、合成试听 |
| `http://localhost:3000/pet` | **Web 桌宠**（供 WebEngine 嵌入，`?embed=qt` 透明模式） |

Web 设置面板可批量保存 LLM / TTS / MCP / ASR / 记忆 / 角色 / 翻译配置。

### Live2D 桌宠

**双击 `启动桌宠.bat`**，或：

```powershell
python scripts/run_pet.py                    # 仅 API + 原生桌宠
python scripts/launcher.py --pet             # 原生 Live2D（PySide6 + live2d-py）
python scripts/launcher.py --pet-web         # WebEngine 桌宠
python scripts/launcher.py --pet --warmup-tts  # 桌宠时后台预热 TTS
```

桌宠快捷键与功能：

- **Ctrl+M** — 语音输入（ASR）
- **Ctrl+G** — GIF 面板
- **粘贴截图** — 视觉识图（需配置 DashScope）
- **设置对话框** — 8 个 Tab：界面 / 角色 / 记忆 / 日程与提醒 / LLM / MCP / TTS / ASR

### 命令行工具

```powershell
# ASR
python cli/asr.py --stream --language zh     # 实时流式识别
python cli/asr.py --mic --language zh        # 录音转写
python cli/asr.py audio.wav                  # 文件转写
python cli/asr.py --list-devices             # 列出音频设备

# TTS
python cli/tts.py "你好" -o out.wav
python cli/tts.py --check                    # 检查 TTS 服务
python cli/tts.py --start-server             # 启动 GPT-SoVITS 9880

# 安装 -e . 后可用短命令
pnn-asr --stream --language zh
pnn-tts "你好" -o out.wav
```

### 仅启动 API

```powershell
python -m server.main
# 健康检查：http://127.0.0.1:8765/api/health
```

## 环境变量（`.env`）

复制 `.env.example` 为 `.env`，**勿提交 `.env` 到 Git**。

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | LLM API 密钥（**必需**） |
| `DEEPSEEK_BASE_URL` | API 地址，默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 对话模型，默认 `deepseek-chat` |
| `AGENT_MODEL` | MCP Agent 模型（搜网页/改代码），默认 `deepseek-v4-pro` |
| `DASHSCOPE_API_KEY` | 阿里云视觉识图（粘贴截图功能） |
| `PNN_API_HOST` / `PNN_API_PORT` | 本地网关，默认 `127.0.0.1:8765` |
| `TTS_SERVER_URL` | GPT-SoVITS 地址，默认 `http://127.0.0.1:9880` |
| `TTS_API_KEY` | 云 TTS 密钥（CosyVoice 等，可选） |
| `BAIDU_TRANSLATE_APP_ID` / `BAIDU_TRANSLATE_SECRET` | 气泡显示中文翻译（TTS 仍用 AI 原文） |
| `HF_ENDPOINT` | HuggingFace 镜像，默认 `https://hf-mirror.com` |

完整列表见 [.env.example](.env.example)。

## 模型与资源路径

### ASR（Whisper）

```
models/ASR/whisper/faster_whisper_tiny/
models/ASR/whisper/faster_whisper_small/
```

首次使用可从 HuggingFace 自动下载（建议配置 `HF_ENDPOINT` 镜像）。

### TTS（GPT-SoVITS）

```
models/TTS/GPT-SoVITS-v2pro-20250604/    # 整合包（含 api_v2.py、runtime/python.exe）
models/character/{角色id}/{角色id}.ckpt    # 角色 GPT 权重
models/character/{角色id}/{角色id}.pth    # 角色 SoVITS 权重
data/tts/{角色}/                          # 参考音频
```

详见 [docs/TTS_LOCAL_ASSETS.md](docs/TTS_LOCAL_ASSETS.md)。

### Live2D 桌宠

```
live2d/14酱/                              # 默认 Live2D 模型
data/characters/{角色id}/pack.json        # 角色包（人设、TTS、Live2D 路径）
```

仓库自带角色包：**里想奈、树里亚、塞拉**（含日语 reply_language 配置）。

## 配置说明

业务配置在 `data/config/*.json`（模板在 `config/templates/*.example`）：

| 文件 | 内容 |
|------|------|
| `llm.json` | 模型、提示词、当前角色、temperature |
| `tts.json` | 引擎、9880 地址、权重路径、参考音 |
| `memory.json` | 记忆开关、检索条数、提取与衰减 |
| `mcp.json` | MCP 开关、Playwright/filesystem 服务 |
| `translate.json` | 百度翻译 |
| `pet_ui.json` | 桌宠 UI：字号、气泡、缩放、窗口位置 |
| `presence.json` | 在场感：空闲搭话、AFK、日程触发 |

加载优先级（LLM 密钥）：`data/config/llm.json` → `local_config.py`（可选）→ **`.env` 覆盖**

可在 Web 设置页或桌宠设置对话框中修改，也可直接编辑 JSON。

## MCP 与 Agent

在设置中启用 MCP 并勾选「对话中使用」，即可在聊天中：

- 搜索网页、抓取页面内容
- 读写项目内文件、执行代码编辑
- 处理截图下载等任务

需配置 `AGENT_MODEL`（或 `.env` 中对应变量），并确保 Playwright 浏览器已安装：

```powershell
playwright install chromium
```

## 项目结构

详见 [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md)。

```
pnn_garden/
├── .env.example          # 复制为 .env，填入 API Key
├── apps/web/             # Next.js 前端（ASR / 对话 / TTS）
├── server/               # FastAPI 网关 (8765)
├── pnn/                  # ASR / TTS / LLM / Agent / MCP / 桌宠 pet/
├── cli/                  # pnn-asr / pnn-tts 命令行
├── scripts/              # launcher.py 一键启动、run_pet.py 桌宠
├── data/config/          # 业务配置 JSON（不含密钥）
├── data/characters/      # 角色包 pack.json
├── config/templates/     # 配置模板
├── live2d/14酱/          # Live2D 模型
├── models/               # ASR / TTS 权重（体积大，勿提交 Git）
├── docs/                 # 详细文档
├── launch/               # 启动脚本（被根目录 .bat 调用）
├── 一键启动.bat          # API + 网页
└── 启动桌宠.bat          # API + 原生桌宠
```

## 更多文档

| 文档 | 说明 |
|------|------|
| [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md) | 目录结构与密钥位置 |
| [docs/TTS_LOCAL_ASSETS.md](docs/TTS_LOCAL_ASSETS.md) | TTS 本地资源清单与自检 |
| [docs/MEMORY.md](docs/MEMORY.md) | 长期记忆 RAG 流程 |
| [docs/CODING_GUIDE_zh-CN.md](docs/CODING_GUIDE_zh-CN.md) | 开发规范与 Agent 路由 |
| [docs/ui/风格.md](docs/ui/风格.md) | Obsidian Glass UI 设计规范 |

## 常见问题

**端口 8765 被占用**

```powershell
launch\kill_api_8765.bat
```

**TTS 无声音**

1. 检查 `GET http://127.0.0.1:8765/api/tts/health` 是否 `ok: true`
2. 确认 GPT-SoVITS 整合包路径与角色权重（见 [TTS 文档](docs/TTS_LOCAL_ASSETS.md)）
3. Web 对话页设置 → TTS → 确认引擎与参考音

**桌宠无法启动**

1. 确认已 `pip install PySide6 live2d-py PyOpenGL`
2. 确认 Live2D 模型存在于 `live2d/14酱/` 或角色包指定路径
3. 先确保 API 正常：`python -m server.main`

**截图识图不可用**

DeepSeek 对话 API 不支持图片，需在 `.env` 配置 `DASHSCOPE_API_KEY`（阿里云 Qwen-VL）。
