# 启动入口

仓库：<https://github.com/chisworld/private_robot>

## 根目录（双击）

| 文件 | 作用 |
|------|------|
| `一键启动.bat` | API + Next.js 网页 |
| `启动桌宠.bat` | 原生 Live2D 桌宠 + API |

转发到 `launch/` 下英文路径脚本：

| 脚本 | 作用 |
|------|------|
| `launch/start_garden.bat` | 全站（API + Web） |
| `launch/start_pet.bat` | 桌宠 |
| `launch/start_qwen_local.bat` | 本地 llama-server（NSFW Qwen） |
| `launch/kill_api_8765.bat` | 释放 8765 端口 |

## 命令行

```powershell
python scripts/launcher.py              # 默认打开 /chat
python scripts/launcher.py --pet        # 桌宠
python scripts/launcher.py --pet --warmup-tts
python scripts/run_pet.py               # 仅 API + 桌宠
python -m server.main                   # 仅 API
```

## 首次使用

1. `copy .env.example .env`，填入 `DEEPSEEK_API_KEY`
2. `pip install -r requirements.txt`（含 chromadb）
3. 可选：按 [docs/MODEL_DOWNLOADS.md](../docs/MODEL_DOWNLOADS.md) 下载 TTS / Qwen 到 `models/`
