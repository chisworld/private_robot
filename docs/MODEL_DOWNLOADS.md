# 模型下载地址

大体积权重放在项目根 `models/`，**勿提交 Git**。下列链接可在桌宠 **设置页** 或 Web **ASR / TTS 页** 直接点击打开。

国内用户建议在 `.env` 配置 HuggingFace 镜像：

```env
HF_ENDPOINT=https://hf-mirror.com
```

完整登记见 `pnn/core/model_downloads.py`；也可访问 API：

`GET http://127.0.0.1:8765/api/models/downloads`

---

## ASR（Whisper / faster-whisper）

| 模型 | 安装路径 | 下载 |
|------|----------|------|
| tiny | `models/ASR/whisper/faster_whisper_tiny/` | [Systran/faster-whisper-tiny](https://hf-mirror.com/Systran/faster-whisper-tiny) |
| small（中文推荐） | `models/ASR/whisper/faster_whisper_small/` | [Systran/faster-whisper-small](https://hf-mirror.com/Systran/faster-whisper-small) |

识别中文需**多语言版**，不要下载带 `.en` 的英文专用模型。下载后目录内应含 `model.bin`。

---

## TTS（GPT-SoVITS）

| 资源 | 安装路径 | 下载 |
|------|----------|------|
| v2pro 整合包 | `models/TTS/GPT-SoVITS-v2pro-20250604/` | [GitHub Releases](https://github.com/RVC-Boss/GPT-SoVITS/releases) |
| 角色 GPT / SoVITS | `models/character/{角色id}/` | 自行训练或从角色包 ZIP 导入；见 [训练文档](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md) |

详见 [TTS_LOCAL_ASSETS.md](TTS_LOCAL_ASSETS.md)。

---

## 本地 Qwen（桌宠 NSFW 日常闲聊）

目录：`models/Qwen3.6-35B-A3B-Uncensored/`

| 文件 | 子路径 | 下载 |
|------|--------|------|
| 主模型 `.gguf` | `Models/` | [HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive](https://hf-mirror.com/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive)（选 IQ2_M 等量化版） |
| `llama-server.exe` + CUDA DLL | 整合包根目录 | [llama.cpp Releases](https://github.com/ggerganov/llama.cpp/releases)（CUDA 构建） |
| mmproj（可选，本地识图） | `Models/` | 同上 HuggingFace 仓库中的 `mmproj*.gguf` |

配置好后：

1. 角色页开启 **NSFW**
2. 启动桌宠（会自动后台拉起 llama-server），或手动运行 `launch/start_qwen_local.bat`

识图默认走 DashScope 云端（`.env` 中 `DASHSCOPE_API_KEY`），无需 mmproj。
