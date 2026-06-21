# 给别人安装 — 用户说明

欢迎使用 **private_robot**（AI 桌宠 + 语音对话）。

## 系统要求

- **Windows 10/11 64 位**
- **Python 3.11 或更高**（[下载 Python](https://www.python.org/downloads/)，安装时勾选 **Add python.exe to PATH**）
- **网络**（首次安装要下载 Python 依赖）
- **DeepSeek API Key**（[platform.deepseek.com](https://platform.deepseek.com/) 注册获取）
- 可选：**NVIDIA 显卡**（本地 TTS / 本地 Qwen 更快；没有也能用文字对话）

## 安装步骤（3 步）

### 1. 解压

把 `private_robot-x.x.x-win64.zip` 解压到任意目录，例如：

```
D:\Apps\private_robot\
```

路径尽量不要含奇怪符号；**不要**放在需要管理员权限的 `Program Files` 里（首次安装要写 `.venv`）。

### 2. 首次安装

双击 **`首次安装.bat`**

- 自动创建 `.venv` 并安装依赖（约 5～15 分钟，视网络而定）
- 按提示输入 **DEEPSEEK_API_KEY**（`sk-` 开头）
- 看到「安装完成」即可

若跳过 Key，稍后编辑文件夹里的 **`.env`**：

```
DEEPSEEK_API_KEY=sk-你的密钥
```

### 3. 启动桌宠

双击 **`启动桌宠.bat`**

- 第一次可能稍慢（后台启动 API）
- 托盘/任务栏出现桌宠窗口后即可对话

## 可选：语音 TTS

默认可以**文字聊天**；要角色说话需要：

1. 打开桌宠 **设置 → 语音 / 角色**，点击 **模型下载链接**
2. 下载 **GPT-SoVITS 整合包** 到 `models/TTS/`（见包内 `docs/MODEL_DOWNLOADS.md`）
3. 下载对应角色的 **GPT/SoVITS 权重** 到 `models/character/{角色名}/`
4. 在设置里保存并等待 TTS 预热

角色参考音已包含在压缩包内的 `data/tts/`。

## 可选：本地 NSFW / 离线闲聊

需要额外下载 **Qwen GGUF + llama-server**（体积大，见 `docs/MODEL_DOWNLOADS.md`），在角色设置里开启 NSFW。

## 常见问题

| 问题 | 处理 |
|------|------|
| 找不到 python | 重装 Python 3.11+，勾选 Add to PATH，重启电脑 |
| 端口 8765 被占用 | 运行 `launch\kill_api_8765.bat` |
| 没声音 | 先配好 GPT-SoVITS；设置 → 语音里看 TTS 状态 |
| 桌宠闪退 | 看 `data\logs\api_boot.log`；重新运行「首次安装.bat」 |
| 记忆/设置丢了 | 都在解压目录的 `data\` 下，换目录解压会重新开始 |

## 隐私说明

- **`.env` 里的 API Key 只在你电脑上**，不会上传到我们仓库
- 对话记忆在 `data/memory/{角色}/`，卸载时删除整个文件夹即可

## 更多文档

解压包内的 `docs/` 目录有完整说明；模型下载见 `docs/MODEL_DOWNLOADS.md`。
