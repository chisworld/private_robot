# 桌宠长期记忆（RAG）

## 流程

1. 主人发话 → 按语义检索 Top-K 条记忆 + 核心设定 + 好感/心情 → 注入 System Prompt  
2. 大模型流式回复（桌宠表情 Prompt 仍单独注入）  
3. 后台第二轮 LLM（可选）：判断是否写入长期事实记忆（JSON）  
4. **记忆写入**：每轮 LLM 提取 — 必填 `chat_summary` 写入 `kind=chat`（概括对话，**不含表情名**）；可选 `fact/event` 等事实条；翻译开启时按译文；`id` 为本地时间  
5. **日记**：仍在退出桌宠 / 关闭 API / 切换角色时合并写入（每天最多一篇；入库前去掉 `【表情:…】` 标签）  
6. 按天衰减低分记忆；与已有记忆相似时，默认用大模型**合并**（处理矛盾/喜好更新），可关闭  

## 配置

复制 `config/templates/memory.json.example` 为 `data/config/memory.json`（**仅引擎参数**，不含具体角色性格）。

角色性格、记忆核心设定写在 `data/characters/{角色ID}/pack.json`（你当前只有 **树里亚**，Live2D 外形目录为 `live2d/14酱`，二者不是同一个名字）。

| 字段 | 说明 |
|------|------|
| `core_card` | 全局默认核心人设；**优先使用当前角色包** `data/characters/{id}/pack.json` 的 `memory.core_card` |
| `merge_similar_with_llm` | 相似记忆是否调用 LLM 合并（默认 true） |
| `top_k` | 每轮检索条数，默认 5 |
| `extraction_enabled` | 是否自动提取记忆 |
| `decay_per_day` | 每日记忆活跃度衰减 |
| `diary_enabled` | 退出桌宠/API 时将会话内对话批量写入日记（每天最多一篇） |

记忆按 `llm.json` 的 `active_character` 分库（如 `树里亚`）。

## 角色包

每个角色一份 `data/characters/{id}/pack.json`，包含：

- `character_prompt` — 人物设定  
- `live2d.model_dir` — Live2D 目录（相对项目根）  
- `tts` — 参考音、参考文本等  
- `memory.core_card` — 该角色专属核心记忆  

在桌宠 **设置 → 角色** 切换并应用；**设置 → 记忆** 可查看/删除当前角色记忆条目。

API：`GET/PUT /api/characters/packs/{id}`、`POST /api/characters/packs/{id}/apply`

## 向量库

安装可选依赖后启用 Chroma 语义检索：

```bash
pip install chromadb
```

未安装时使用本地关键词相似度回退，仍可运行。

## API

- `GET /api/memory/config`  
- `PUT /api/memory/config`  
- `GET /api/memory/list`  
- `DELETE /api/memory/{id}`  
- `POST /api/memory/diary` — 手动写日记  

## 写入时机

- **每轮对话**：`extraction_enabled` 时写入 `[chat]` 轮次摘要 + 可选 `[event]`/`[fact]` 等（列表形如 `id | [chat] 摘要`）。  
- **退出 / 关 API / 切角色**：`diary_enabled` 时合并本会话写一篇日记。  
- 手动：`POST /api/memory/diary`，body: `{"summary": "..."}`。

## 三类设定区别（常见疑问）

| 配置项 | 位置 | 作用 |
|--------|------|------|
| **人物设定** `character_prompt` | 设置 → 角色 | 注入 LLM 的完整人设、口癖、剧情；决定**怎么说话** |
| **记忆核心** `memory.core_card` | 设置 → 角色（同步到记忆页） | 注入记忆的「永不覆盖」块；可写名字、关系（如称用户为「主人」） |
| **记忆页 core_card** | 设置 → 记忆 | 与角色包同源，改一处会同步；引擎参数在 `memory.json` |

`character_prompt` 管扮演；`core_card` 管长期记忆检索时始终带上的关系/身份摘要。
