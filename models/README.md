# 模型权重目录

本目录存放**体积较大的 AI 权重**，默认 **不提交 Git**（见根目录 `.gitignore`）。

仓库：<https://github.com/chisworld/private_robot>

## 目录结构

```
models/
├── ASR/whisper/              # faster-whisper（tiny / small）
├── TTS/GPT-SoVITS-v2pro-*/   # GPT-SoVITS 整合包
├── character/{角色id}/       # 角色 GPT (.ckpt) + SoVITS (.pth)
└── Qwen3.6-35B-A3B-Uncensored/  # 本地 llama-server + GGUF（NSFW 闲聊）
```

## 下载

所有公开下载链接见 [docs/MODEL_DOWNLOADS.md](../docs/MODEL_DOWNLOADS.md)。

桌宠 **设置 → 角色 / TTS / ASR** 底部也有可点击链接；API：`GET /api/models/downloads`。

## 与仓库内资源的区别

| 资源 | 位置 | 是否在 Git |
|------|------|------------|
| Live2D 立绘 | `live2d/`、`apps/web/public/live2d/models/` | ✅ 已入库 |
| TTS 参考音 | `data/tts/{角色}/reference.wav` | ✅ 已入库 |
| 记忆库 | `data/memory/{角色}/` | ✅ 已入库 |
| LLM / TTS 权重 | 本目录 `models/` | ❌ 本地下载 |
