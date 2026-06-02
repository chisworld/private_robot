# TTS 本地资源清单

为减少启动时网络下载与首次合成延迟，以下资源应**提前放在本机**。程序启动时会通过 `tts_service.bootstrap()` 加载 `data/config/tts.json`，并合并当前角色包（`data/characters/{id}/pack.json`）中的 TTS 字段；API 启动后会在后台执行 `preload` 拉起 GPT-SoVITS（9880）并切换权重。

## 必装（GPT-SoVITS）

| 资源 | 推荐路径 | 说明 |
|------|----------|------|
| GPT-SoVITS 整合包 | `models/TTS/GPT-SoVITS-v2pro-20250604/` | 须含 `api_v2.py`、`runtime/python.exe`；勿在运行时从 GitHub 拉取 |
| 默认预训练权重 | 整合包内 `GPT_SoVITS/pretrained_models/` | `tts.json` 未指定角色权重时使用 |
| 角色 GPT 权重 | `models/character/{角色id}/{角色id}.ckpt` | 对应 `gpt_model_path` |
| 角色 SoVITS 权重 | `models/character/{角色id}/{角色id}.pth` | 对应 `sovits_model_path` |
| 参考音频 | `data/tts/reference/character_ref.wav` | 角色音色；首次会从配置路径镜像到此目录 |
| 参考提示词 | `data/config/tts.json` → `prompt_text` | 与参考音频同语言，建议与音频内容一致 |

## 可选（其它引擎）

| 资源 | 路径 | 说明 |
|------|------|------|
| Index TTS / Genie | 各自 `work_path` | 与 GPT-SoVITS 类似，整包放本地 |
| CosyVoice | 阿里云 API Key | 走云端，无本地 9880 |

## 配置入口

- 全局：`data/config/tts.json`（可由设置页保存）
- 角色：`data/characters/{角色id}/pack.json` → `tts` 段；应用角色时会写入 `tts.json`
- 环境变量：`.env` 中 `TTS_SERVER_URL`、`TTS_API_KEY`（可选）

## 启动行为

1. **API `on_startup`**：`bootstrap()` 读配置 → 后台 `preload()` 起 9880 → 就绪后 `switch_model` 一次。
2. **桌宠**：`ServiceWarmupWorker` 调用 `POST /api/tts/preload`，最多等待 120s 显示「TTS 已就绪」。
3. **合成**：不再每次从磁盘重载配置（按 `tts.json` 修改时间刷新）；已切换的模型路径会跳过重复 `set_gpt_weights` / `set_sovits_weights`。

## 迁移建议

新角色请在 `models/character/{角色id}/` 下放置 `{角色id}.ckpt` 与 `{角色id}.pth`，并在角色包 `pack.json` 的 `tts` 段填写相对路径。

## 自检

启动 API 后访问：

- `GET http://127.0.0.1:8765/api/tts/config` → 查看 `asset_warnings`
- `GET http://127.0.0.1:8765/api/tts/health` → `ok: true` 表示 9880 已响应
