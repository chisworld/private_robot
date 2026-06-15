# PNN Garden / private_robot 目录说明

仓库：<https://github.com/chisworld/private_robot>

## 顶层分类

| 目录 / 文件 | 类别 | 说明 |
|-------------|------|------|
| `apps/web/` | 前端 | Next.js（对话 / TTS / 桌宠页） |
| `server/` | 后端网关 | FastAPI 8765 |
| `pnn/` | 核心库 | ASR、TTS、LLM、记忆、桌宠 `pet/` |
| `cli/` | 命令行 | `asr.py`、`tts.py` |
| `scripts/` | 脚本 | `launcher.py`、`run_pet.py` |
| `data/` | 数据与配置 | **记忆库、角色包、config 已入库 Git** |
| `cache/` | 运行缓存（勿提交） | TTS 音频、临时文件 |
| `config/` | 配置模板 | `templates/*.example` |
| `live2d/` | Live2D 模型 | **已入库**：里想奈、塞拉、14酱 等 |
| `apps/web/public/live2d/models/` | Web Live2D | 与 `live2d/` 部分镜像 |
| `models/` | 大权重（勿提交） | ASR / TTS / Qwen；见 `models/README.md` |
| `docs/` | 文档 | MEMORY、MODEL_DOWNLOADS、开发规范 |
| `launch/` | 启动脚本 | `start_pet.bat`、`start_qwen_local.bat` |
| `.env` | 密钥（本地） | **勿提交** |

## 密钥与配置

1. **API Key** → 根目录 `.env`（从 `.env.example` 复制）
2. 业务参数 → `data/config/*.json`
3. 可选 → `local_config.py`

加载顺序（LLM）：`llm.json` → `local_config.py` → **`.env` 覆盖密钥**

## 记忆与 ChromaDB

```
data/memory/{角色ID}/
├── memories.json
├── state.json
└── chroma/              # chromadb PersistentClient
```

依赖：`requirements.txt` → `chromadb>=0.5.0`  
模块：`pnn/memory/store.py`

## 桌宠相关

| 路径 | 说明 |
|------|------|
| `pnn/pet/` | PySide6 三窗口桌宠 |
| `live2d/里想奈/`、`live2d/塞拉/`、`live2d/14酱/` | 原生桌宠模型 |
| `data/config/pet_ui.json` | 气泡、缩放、窗口位置 |
| `data/config/presence.json` | 空闲搭话、番茄、提醒 |
| `data/config/llm.json` | NSFW、本地 Qwen URL |

## 勿提交 Git

- `models/` 内权重（`!/models/README.md` 除外）
- `.env`、`.venv/`
- `cache/`、`data/logs/`
