# 启动入口

## 根目录（双击即可）

| 文件 | 作用 |
|------|------|
| `一键启动.bat` | 启动 API + Next.js 网页 |
| `启动桌宠.bat` | 原生 Live2D 桌宠（自动起 API 8765） |

二者会调用本目录下的 **英文路径** 脚本（避免 cmd 无法识别中文文件名）：

- `launch/start_pet.bat` — 桌宠
- `launch/start_garden.bat` — 全站

## 命令行

```powershell
python scripts/launcher.py
python scripts/launcher.py --pet
```

首次使用：复制 `.env.example` 为 `.env`，填入 `DEEPSEEK_API_KEY`。
