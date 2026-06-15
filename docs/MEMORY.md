# 桌宠长期记忆（RAG）

仓库：<https://github.com/chisworld/private_robot>

## 流程

1. 主人发话 → ChromaDB 向量检索 + 关键词混合排序 Top-K → 注入 System Prompt（含核心设定）
2. 大模型流式回复（桌宠表情 Prompt 单独注入）
3. 后台可选 DeepSeek 提取 `[fact]` / `[event]`（`extraction_enabled`）
4. **每轮写入 `[dialogue]`**：完整一轮 user/assistant 对话块（去表情标签；非中文角色存【中文】块）
5. **空闲搭话 / 日程提醒**：系统主动开口后同样写入 `[dialogue]`，用户侧标记为 `空闲搭话·…` 或 `日程提醒·…`（不跑 fact 提取）
6. **日记**：退出桌宠 / 关 API / 切角色时合并会话缓冲（`diary_enabled`）
7. 按天衰减低分记忆；相似记忆默认 LLM 合并（可关）

## ChromaDB 向量库

### 依赖

`chromadb>=0.5.0` 已在根目录 `requirements.txt` 中，执行 `pip install -r requirements.txt` 即可。

### 存储路径

```
data/memory/{角色ID}/
├── memories.json    # 主 JSON 存储（所有 kind）
├── state.json       # 去重、会话状态
└── chroma/          # PersistentClient 向量索引（自动创建/同步）
```

实现：`pnn/memory/store.py` — `MemoryStore._init_chroma()`、`search()` 混合 Chroma 距离 + 关键词相关度。

### 运行时自检

```powershell
python -c "from pnn.memory.store import _chroma_available, MemoryStore; print('ChromaDB:', _chroma_available()); s=MemoryStore('里想奈'); print('collection:', s._collection is not None)"
```

- 当前环境（`.venv`）已验证：**chromadb 1.5.9**，PersistentClient 读写正常，`MemoryStore` 可创建 collection。
- 桌宠 **设置 → 记忆** 页脚：`向量检索已启用` / `仅关键词检索`（来自 `memory_stats` 的 `chroma_available`）。

### 未安装时的回退

若 `import chromadb` 失败，自动使用 **JSON + 关键词相似度**，不影响桌宠运行；日志会提示 `pip install chromadb`。

## 配置

模板：`config/templates/memory.json.example` → `data/config/memory.json`

| 字段 | 说明 |
|------|------|
| `enabled` | 总开关 |
| `extraction_enabled` | 是否 DeepSeek 提取 fact/event |
| `top_k` | 每轮检索条数，默认 5 |
| `merge_similar_with_llm` | 相似记忆 LLM 合并 |
| `decay_per_day` | 每日活跃度衰减 |
| `diary_enabled` | 退出时写会话日记 |

角色核心设定在 `data/characters/{id}/pack.json` → `memory.core_card`（优先于全局）。

记忆按 `llm.json` 的 `active_character` 分库。

## 角色包

`data/characters/{id}/pack.json`：

- `character_prompt` — 人设
- `live2d.model_dir` — 如 `live2d/里想奈`（仓库已含 Live2D 资源）
- `reply_language` — `ja` / `zh`（非中文角色启用双语【中文】块）
- `tts` — 参考音路径
- `memory.core_card` — 长期关系摘要

自带角色：**里想奈、树里亚、塞拉**。

## 写入时机

| 场景 | 写入内容 | 提取 fact |
|------|----------|-----------|
| 用户正常对话 | `[dialogue]` + 可选 fact/event | ✅ |
| 空闲搭话 / 时段问候 / 久别重逢等 | `[dialogue]`，用户行 `空闲搭话·{背景摘要}` | ❌ |
| 日程到点提醒 | `[dialogue]`，用户行 `日程提醒·…` | ❌ |
| 退出 / 切角色 | 会话日记（若开启） | — |

代码入口：`pnn/pet/controller.py` → `_notify_memory_turn`；`pnn/memory/service.py` → `after_conversation_turn`。

## 双语与展示

非中文角色（`reply_language=ja`）：

- TTS 读日语段；气泡/终端/记忆优先模型输出的 `【中文】` 块
- `pnn/pet/chinese_display.py` 清理漏写的假名

详见 `pnn/pet/bilingual_reply.py`、`pnn/pet/reply_text.py`。

## API

- `GET /api/memory/config`
- `PUT /api/memory/config`
- `GET /api/memory/list`
- `DELETE /api/memory/{id}`
- `POST /api/memory/diary`

## 三类设定区别

| 配置项 | 位置 | 作用 |
|--------|------|------|
| **人物设定** | 角色 pack `character_prompt` | 怎么说话、性格 |
| **记忆核心** | pack `memory.core_card` | 检索时始终带上的关系/身份 |
| **引擎参数** | `memory.json` | top_k、提取、衰减 |
