# PNN Garden 目录说明

## 顶层分类

| 目录 / 文件 | 类别 | 说明 |
|-------------|------|------|
| `apps/web/` | 前端 | Next.js 网页（对话 / TTS / 桌宠页） |
| `server/` | 后端网关 | FastAPI，统一 ASR / TTS / LLM API |
| `pnn/` | 核心能力库 | ASR、TTS、LLM、桌宠 `pet/` 等 Python 模块 |
| `cli/` | 命令行工具 | 如 `cli/asr.py` |
| `scripts/` | 运维脚本 | `launcher.py` 一键启动、`run_pet.py` 等 |
| `data/` | 数据与运行时配置 | `config/*.json`、模型、TTS 输出 |
| `config/` | 配置模板 | `templates/*.example`；说明见 `config/README.md` |
| `live2d/` | Live2D 模型 | 桌宠模型，如 `live2d/14酱/` |
| `docs/` | 文档 | 本文件、UI 设计规范 `docs/ui/` |
| `launch/` | 启动说明 | 根目录 `.bat` 入口说明 |
| `CUDA_DLL/` | 运行依赖 | GPU 相关 DLL |
| `.env` | **密钥（本地）** | 从 `.env.example` 复制，**勿提交 Git** |
| `一键启动.bat` / `启动桌宠.bat` | 快捷启动 | 转发到 `launch/` 内实际脚本 |

## 密钥与配置放在哪？

1. **API Key、Base URL** → 项目根 **`.env`**（推荐）
2. 业务参数（提示词、角色、TTS 路径）→ `data/config/*.json`
3. 可选旧方式 → `local_config.py`（见 `local_config.example.py`）

加载优先级（LLM）：`data/config/llm.json` → `local_config.py` → **`.env` 覆盖密钥**

## 桌宠相关

| 路径 | 说明 |
|------|------|
| `pnn/pet/` | 原生 PySide6 桌宠 |
| `live2d/14酱/` | Live2D 模型（自 `launch/assets/live2d` 迁到项目根） |
| `models/ASR/` | Whisper 等语音识别模型 |
| `models/TTS/` | GPT-SoVITS 等语音合成整合包 |
| `data/config/pet_ui.json` | 气泡字号、人物缩放等 |

## 不建议改动的目录

- `models/` — 体积大，ASR / TTS 权重（勿提交 Git 大文件）
- ~~`data/models/`~~ — 已废弃，TTS 整合包统一放在 `models/TTS/`
- `apps/web/node_modules/`、`apps/web/.next/` — 前端依赖与构建产物
