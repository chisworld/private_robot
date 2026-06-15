# Live2D 模型目录

仓库：<https://github.com/chisworld/private_robot>

桌宠 Live2D 资源**已纳入 Git**，克隆后即可使用。

## 目录结构

```
live2d/
├── 14酱/               # 树里亚
├── 里想奈/             # 血裔少女
├── 塞拉/
│   ├── pink_devil/
│   └── xizaozhao/
└── 吸血姬模型本体/     # 备用副本
```

Web 桌宠镜像：`apps/web/public/live2d/models/`（14酱、吸血姬）

## 角色包绑定

`data/characters/{id}/pack.json` → `live2d.model_dir`，如 `live2d/里想奈`。

桌宠 **设置 → 角色 → 应用角色** 会重载 Live2D。

## 自定义路径

```
LIVE2D_MODEL_DIR=D:/你的路径/模型目录
```

旧路径 `assets/live2d/` 仍会被程序识别。
