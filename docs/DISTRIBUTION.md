# 打包分发给他人

面向**维护者**：如何把 private_robot 打成 zip 发给朋友安装。

## 分发形态

当前采用 **便携 zip + 首次安装脚本**（不打包成单一 exe）：

- 含 Live2D、角色包、参考音（体积约数百 MB）
- **不含** LLM/TTS/Whisper 大权重（用户按需下载）
- **不含** 你的 `.env`、个人记忆、`data/config` 里的密钥

对方流程：**解压 → 首次安装.bat → 启动桌宠.bat**

## 一键打包

在项目根目录 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
# 指定版本号
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1 -Version 0.2.0
```

输出：

```
dist/private_robot-0.2.0-win64.zip
dist/private_robot-0.2.0/          # 未压缩目录（便于检查）
```

压缩包内自带 **`安装说明.md`**（来自 `docs/INSTALL_FOR_USERS.md`）。

## 打包排除项

| 排除 | 原因 |
|------|------|
| `.venv/`、`models/` | 对方本机生成 / 自行下载 |
| `.env` | 密钥 |
| `data/memory/`、`data/presence/` | 个人数据 |
| `data/config/*.json` | 含 Key 或本机路径；首次安装从 `config/templates/` 生成 |
| `node_modules/`、`.next/` | Web 可选；对方用桌宠可不装 Node |
| `.git/` | 体积 |

## 发给对方前检查清单

- [ ] 自己运行 `scripts\package_release.ps1` 成功
- [ ] 在**干净目录**解压 zip，跑通 `首次安装.bat` + `启动桌宠.bat`
- [ ] 确认 zip 内**没有**你的 `.env` 和 `data/memory`
- [ ] 告知对方：必须有 **Python 3.11+** 和 **DeepSeek Key**
- [ ] 可选：单独说明 TTS / Qwen 下载方式（`docs/MODEL_DOWNLOADS.md`）

## 首次安装脚本

| 文件 | 作用 |
|------|------|
| `首次安装.bat` | 用户入口 |
| `launch/first_run_setup.bat` | 调用 Python |
| `scripts/first_run_setup.py` | 创建 venv、pip install、`.env`、config 模板 |

标记文件：`.install_done`（安装成功后生成；打包时不会包含）

重新安装依赖：

```powershell
.\.venv\Scripts\python.exe scripts\first_run_setup.py
# 或强制重装 pip
.\.venv\Scripts\python.exe scripts\first_run_setup.py --skip-pip
del .install_done
首次安装.bat
```

## Web 版（可选）

若对方需要浏览器 `localhost:3000`：

1. 安装 [Node.js 18+](https://nodejs.org/)
2. 在项目根：`cd apps\web && npm install && npm run dev`
3. 或使用 `一键启动.bat`（会起 API + Web）

便携 zip **不含** `node_modules`，首次需联网 `npm install`。

## 后续：安装包 exe（未实现）

若要 Inno Setup / PyInstaller 单文件安装器，需额外处理 PySide6 + Live2D + 多子进程；当前 zip 方案更稳。

## 相关文档

- [INSTALL_FOR_USERS.md](INSTALL_FOR_USERS.md) — 给最终用户
- [MODEL_DOWNLOADS.md](MODEL_DOWNLOADS.md) — 模型下载
- [README.md](../README.md) — 项目总览
