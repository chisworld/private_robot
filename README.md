# private_robot（PNN Garden）

仓库：<https://github.com/chisworld/private_robot>

本地 AI 陪伴与 Agent 平台：**语音识别 · 语音合成 · LLM 对话 · MCP 工具 · Live2D 桌宠 · 长期记忆（ChromaDB）**，可在本机运行，通过对话让 AI 帮你做事或陪伴。

## 功能概览

| 模块 | 说明 |
|------|------|
| **ASR** | faster-whisper 实时/文件语音识别，Web 页与 CLI 均可用 |
| **TTS** | GPT-SoVITS（默认）、Genie TTS、Index TTS、CosyVoice 云；分句朗读、口型同步 |
| **LLM** | DeepSeek / OpenAI 兼容 API，SSE 流式；可选本地 Qwen（NSFW 闲聊） |
| **双语回复** | 日语 TTS + 【中文】界面/记忆（非中文角色） |
| **Agent + MCP** | 网页搜索、项目内改代码、截图任务等多步工具调用 |
| **视觉识图** | 粘贴/上传截图，经 DashScope VL（Qwen-VL）识别 |
| **角色包** | 多角色人设、Live2D、TTS 音色一键切换 |
| **长期记忆** | ChromaDB 向量 RAG + 关键词回退；自动提取；空闲搭话也入库 |
| **在场感 / 提醒** | 空闲主动搭话、番茄钟、日程提取与到期提醒 |
| **系统操控** | 音量/亮度/音乐/关机等（桌宠设置 → 工具） |
| **Web 前端** | Next.js 深色 UI：ASR / 语音对话 / TTS 调试 |
| **Live2D 桌宠** | 原生 PySide6 三窗口，或 WebEngine 嵌入模式 |

## 环境要求

- **Python 3.11+**
- **Node.js 18+**（Web 模式）
- **Windows**（批处理启动脚本；Linux/macOS 可用命令行等价方式）
- 至少填写 `.env` 中的 `DEEPSEEK_API_KEY`
- `pip install -r requirements.txt` 含 **chromadb**（记忆向量检索；缺失时自动关键词回退）
- TTS 需本地 [GPT-SoVITS 整合包](docs/TTS_LOCAL_ASSETS.md)（可选）
- 桌宠需 PySide6、live2d-py（见 `requirements.txt`）
- NSFW 本地闲聊需下载 Qwen GGUF + llama-server（见 [MODEL_DOWNLOADS.md](docs/MODEL_DOWNLOADS.md)）

## 快速开始

### 1. 克隆与依赖

```powershell
git clone https://github.com/chisworld/private_robot.git
cd private_robot

python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt
pip install -e .   # 可选：pnn-garden / pnn-asr / pnn-tts 命令
```

### 2. 配置密钥

```powershell
copy .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY=sk-...
```

### 3. 一键启动

**双击 `一键启动.bat`**，或：

```powershell
python scripts/launcher.py              # 默认 /chat
python scripts/launcher.py --page asr
python scripts/launcher.py --page tts
python scripts/launcher.py --no-browser
python scripts/launcher.py --pet        # 原生桌宠
python scripts/launcher.py --pet --warmup-tts
```

启动器会：检查依赖 → 拉起 API（`127.0.0.1:8765`）与 Web（`localhost:3000`）→ 可选预热 TTS → 打开浏览器。

## 使用方式

### Web 页面

| 地址 | 功能 |
|------|------|
| `http://localhost:3000/` | 语音转文字（流式 ASR、文件转写） |
| `http://localhost:3000/chat` | 语音对话：SSE LLM、ASR、TTS、Live2D |
| `http://localhost:3000/tts` | TTS 调试与试听 |
| `http://localhost:3000/pet` | Web 桌宠（`?embed=qt` 透明模式） |

### Live2D 桌宠

```powershell
python scripts/run_pet.py
python scripts/launcher.py --pet
```

快捷键：**Ctrl+M** 语音 · **Ctrl+G** GIF · **粘贴** 截图识图 · 托盘/设置对话框

设置 8 栏：**界面 / 角色 / 记忆 / 日程 / 对话 / 工具 / 语音**

### 命令行

```powershell
python cli/asr.py --stream --language zh
python cli/tts.py "你好" -o out.wav
python -m server.main   # 仅 API
```

## ChromaDB 记忆向量库

`requirements.txt` 已包含 `chromadb`。安装后每角色记忆目录为：

```
data/memory/{角色ID}/memories.json   # 主存储
data/memory/{角色ID}/chroma/         # Chroma PersistentClient 向量索引
```

**自检（项目根、已激活 venv）：**

```powershell
python -c "from pnn.memory.store import _chroma_available; print('ChromaDB:', _chroma_available())"
```

桌宠 **设置 → 记忆** 页脚会显示「向量检索已启用」或「仅关键词检索」。详见 [docs/MEMORY.md](docs/MEMORY.md)。

## 环境变量（`.env`）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | LLM API 密钥（**必需**） |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 日常对话模型 |
| `AGENT_MODEL` | MCP Agent 模型，默认 `deepseek-v4-pro` |
| `DASHSCOPE_API_KEY` | 阿里云视觉识图 |
| `PNN_API_HOST` / `PNN_API_PORT` | 本地网关，默认 `127.0.0.1:8765` |
| `TTS_SERVER_URL` | GPT-SoVITS，默认 `http://127.0.0.1:9880` |
| `BAIDU_TRANSLATE_APP_ID` / `BAIDU_TRANSLATE_SECRET` | 气泡中文翻译 |
| `HF_ENDPOINT` | HuggingFace 镜像，默认 `https://hf-mirror.com` |

完整列表见 [.env.example](.env.example)。

## 模型与资源

**下载链接**：[docs/MODEL_DOWNLOADS.md](docs/MODEL_DOWNLOADS.md) · API `GET /api/models/downloads` · 桌宠设置页可点击

| 类型 | 路径 | Git |
|------|------|-----|
| ASR Whisper | `models/ASR/whisper/` | ❌ 本地下载 |
| GPT-SoVITS | `models/TTS/GPT-SoVITS-v2pro-*/` | ❌ |
| 角色 TTS 权重 | `models/character/{id}/` | ❌ |
| 本地 Qwen | `models/Qwen3.6-35B-A3B-Uncensored/` | ❌ |
| Live2D | `live2d/`、`apps/web/public/live2d/models/` | ✅ 已入库 |
| 记忆库 | `data/memory/` | ✅ |
| 角色包 | `data/characters/` | ✅ |

自带角色：**里想奈、树里亚、塞拉**（含日语 `reply_language`、参考音、Live2D）。

## 配置说明

业务配置在 `data/config/*.json`（模板：`config/templates/*.example`）：

| 文件 | 内容 |
|------|------|
| `llm.json` | 模型、NSFW、本地 Qwen URL |
| `tts.json` | 引擎、9880、权重路径 |
| `memory.json` | 记忆开关、top_k、提取与衰减 |
| `mcp.json` | MCP 服务列表 |
| `presence.json` | 空闲搭话、番茄、问候 |
| `pet_ui.json` | 桌宠 UI 布局 |

加载优先级（LLM 密钥）：`llm.json` → `local_config.py`（可选）→ **`.env` 覆盖**

## 项目结构

```
private_robot/
├── apps/web/           # Next.js 前端
├── server/             # FastAPI (8765)
├── pnn/                # ASR / TTS / LLM / pet / memory / agent
├── live2d/             # 桌宠 Live2D（里想奈、塞拉、14酱等）
├── data/
│   ├── config/         # 业务 JSON
│   ├── memory/         # 长期记忆 + Chroma
│   └── characters/     # 角色 pack.json
├── models/             # 大权重（勿提交，见 models/README.md）
├── docs/               # 详细文档
├── launch/             # start_pet.bat、start_qwen_local.bat
├── 一键启动.bat
└── 启动桌宠.bat
```

详见 [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md)。

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md) | 目录与密钥位置 |
| [docs/MEMORY.md](docs/MEMORY.md) | 长期记忆与 ChromaDB |
| [docs/MODEL_DOWNLOADS.md](docs/MODEL_DOWNLOADS.md) | 模型下载链接 |
| [docs/TTS_LOCAL_ASSETS.md](docs/TTS_LOCAL_ASSETS.md) | TTS 本地资源 |
| [docs/CODING_GUIDE_zh-CN.md](docs/CODING_GUIDE_zh-CN.md) | 开发规范 |
| [docs/ui/风格.md](docs/ui/风格.md) | Web UI 设计规范 |

## 常见问题

**ChromaDB 未启用**

```powershell
pip install chromadb
python -c "from pnn.memory.store import _chroma_available; print(_chroma_available())"
```

**端口 8765 被占用** → `launch\kill_api_8765.bat`

**TTS 无声音** → `GET /api/tts/health` 应为 `ok: true`；见 [TTS 文档](docs/TTS_LOCAL_ASSETS.md)

**NSFW 未走本地 Qwen** → 角色页开 NSFW；确认终端 `[pet-llm] 本地 Qwen: 就绪`；见 `launch/start_qwen_local.bat`

**截图识图** → 配置 `.env` 中 `DASHSCOPE_API_KEY`
