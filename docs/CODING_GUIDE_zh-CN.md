# PNN Garden 代码规范笔记

> 仓库：<https://github.com/chisworld/private_robot>  
> 路径根目录：`pnn_garden/` / `private_robot/`（桌宠 + API 8765 + Live2D + TTS/ASR/LLM/记忆/MCP）。

---

## 1. 通用原则

1. **最小改动**：只改与需求直接相关的文件；不顺手重构、不扩 scope。
2. **沿用现有抽象**：先读周边代码，命名、分层、import 风格与现有一致。
3. **注释克制**：代码自解释为主；只注释非显而易见的业务规则。
4. **测试要有意义**：覆盖真实行为（语言路由、气泡过滤、Agent 判定等），不写 trivial assert。
5. **不主动 commit**：除非用户明确要求。
6. **Windows 环境**：启动脚本用 `.bat`；Python 优先 conda 环境 `AI`；路径用项目根相对路径或 `pnn.core.paths`。

---

## 2. 项目分层（速查）

| 层级 | 路径 | 职责 |
|------|------|------|
| 桌宠 UI | `pnn/pet/` | 窗口、编排、气泡、TTS 播放、ASR |
| API | `server/` | FastAPI 路由、SSE 流式对话 |
| LLM | `pnn/llm/` | DeepSeek 客户端、system 拼装、角色 store |
| 记忆 | `pnn/memory/` | RAG 检索、提取、合并、会话缓冲 |
| 角色包 | `pnn/characters/` | `pack.json`、reply_language、TTS 绑定 |
| TTS | `pnn/tts/` | GPT-SoVITS 适配、GBK 清理、分句 |
| Agent/MCP | `pnn/agent/`、`pnn/mcp/` | 工具编排、Playwright、任务路由 |
| 翻译 | `pnn/translate/` | 百度 API：气泡中文化 |
| 启动 | `launch/`、`scripts/` | `start_pet.bat`、`launcher.py`、`run_pet.py` |

---

## 3. 多语言与「三通道」文案（核心规范）

每个角色在 `data/characters/{id}/pack.json` 配置 **`reply_language`**（`ja` / `zh`）。  
**所有涉及用户可见/可听输出的功能，必须走统一语言层，禁止硬编码全局日语或中文。**

### 3.1 唯一语言入口

```python
from pnn.characters.reply_lang import active_reply_language, normalize_reply_language, is_japanese
```

- 读配置：`active_reply_language()`
- 规范化：`normalize_reply_language(lang)`
- Agent/截图任务提示：`agent_summary_instruction()`、`screenshot_task_reply_note()` 等同文件函数

### 3.2 三通道分离（必须遵守）

| 通道 | 用途 | 语言规则 |
|------|------|----------|
| **LLM 生成** | 模型原文 | 由 `reply_language` + system 规则约束（日语角色必须日语） |
| **TTS 合成** | 语音朗读 | **必须**传 `text_lang=active_reply_language()`；日语角色若混入中文，先 `tts_text_for_reply()` 译日 |
| **气泡显示** | 界面文字 | 经 `bubble_text_for_reply()` 过滤记忆套话；非中文角色 + 已配百度密钥时译成中文 |

**实现入口**：`pnn/pet/reply_text.py`

```python
from pnn.pet.reply_text import tts_text_for_reply, bubble_text_for_reply
```

### 3.3 TTS 调用 checklist

- [ ] `_TtsWorker` / 任何 `synthesize_tts()` 调用都传 **`text_lang`**
- [ ] 长句用 `split_for_tts()` 分句后再合成、拼接（`concat_wav_bytes`）
- [ ] 发给 GPT-SoVITS 前经 `sanitize_for_gbk_tts(text, lang)`（Windows GBK 兼容）
- [ ] 固定提示语（问候、截图）按语言分文件缓存，如 `screenshot_recognized_ja.wav`

### 3.4 气泡与语音同步

**原则：开语音 = 气泡跟读；不开语音 = 可流式/整段显示。**

#### 语音开启时（`_voice_output_enabled=True`）

| 阶段 | 气泡应显示 | 禁止 |
|------|-----------|------|
| 用户发送 → LLM 思考 | `…` | 整段回复、流式累加全文 |
| LLM 流式 delta | 保持 `…`（或不变） | `_on_chat_delta` 调 `_schedule_display_translate` |
| 对话完成 → 首句 TTS 就绪 | 保持 `…` | `_on_chat_done` 展示完整 `clean` 回复 |
| 每句音频开始播放 | **仅该句**（经 `bubble_text_for_reply` + 可选翻译） | 整段回复 |
| 全部播完 | 清空或按 `app.py` 定时关闭 | — |

**实现要点（`pnn/pet/controller.py`）：**

1. `_on_chat_delta`：仅当 `stream_bubble_output and not _voice_output_enabled` 才更新气泡。
2. `_on_chat_done`（语音分支）：`bubble_translate_seq += 1` 作废流式阶段未完成的翻译；气泡设 `…`；不调用整段 `_schedule_display_translate`。
3. `_show_segment_bubble`：每句播放前调用，带 `bubble_seq` 走翻译。
4. `_play_audio`：语音模式下**不再** `bubble_changed.emit`（避免与分句翻译重复/竞态）。
5. `_schedule_display_translate`：语音模式下 `bubble_seq is None` 的回调一律丢弃（防迟到的整段翻译闪现）。

#### 语音关闭时

- 可开启 `stream_bubble_output`（设置 → 流式气泡）：delta 节流 ~200ms 刷新整段 growing 文本。
- 无 TTS 时 `_on_chat_done` 一次性展示完整回复。

#### 其他

- 合成阶段（TTS worker 运行中）不刷气泡，避免与播放句叠两个框。
- 分句播放：一句音频 ↔ 一句气泡；`MAX_TTS_SEGMENTS = 12`，`_seg_seen` 去重。
- 设置项 `stream_bubble_output` 与语音输出**互斥生效**：用户勾选流式气泡且开语音时，仍按「逐句跟读」行为执行。

```
用户发送 ──► … ──► [LLM 流式，气泡不变] ──► … ──► 句1播放+气泡句1 ──► 句2… ──► 播完清空
```

---

## 4. 记忆系统规范

### 4.1 对用户不可见「后台记忆」

记忆注入在 **system prompt**（`memory_service.build_prompt_context`），用户不应感知 RAG 存在。

**LLM 规则（须写入 system）：**

- 使用记忆时自然融入对话；
- **禁止**对用户说「根据记忆」「我想起」「思い出した」「塞拉的记忆里…」等元叙述；
- **禁止**输出记忆提取摘要口吻（如「主人询问…塞拉记得…并提到是…告诉她的」）。

**气泡规则（代码强制）：**

- 所有进气泡的文本必须过 `bubble_text_for_reply()`；
- 整句含 `记忆里`、`好好记着`、`记性`、`想起` 等 → **整句丢弃**；
- 记忆写入日志（`logger.info("已写入记忆…")`）** never** 进 UI。

### 4.2 记忆检索

- 模块：`pnn/memory/retrieval.py`（问句扩展、脏数据判定、命中去重）。
- `MemoryStore.search()`：**ChromaDB + 关键词混合排序** + `expand_search_query`（「你妹妹」→「{当前角色名} 的妹妹 …」）。Chroma 依赖 `requirements.txt` 中的 `chromadb`；未安装时关键词回退。向量数据在 `data/memory/{id}/chroma/`。
- `active_assistant_label()` / `_dialogue_labels()` 读取当前激活角色，**禁止**在检索逻辑里写死任何角色名或 NPC 名。
- `fact` 优先；`chat` 摘要降权；假遗忘 `chat/event` **检索阶段跳过**。
- 命中 `dedupe_hits` 去重，prompt 里带 `[fact]` / `[event]` 标签。
- 每日首次对话前 `purge_negative_memories()` 自动清理历史假遗忘条目。
- 终端 INFO：`记忆检索 query=… expanded=… 命中 N 条`。

### 4.3 入库过滤

- `store.add` / chat 摘要 / fact 提取：**拒绝或跳过** `is_negative_memory()` 内容。
- 提取器 `content` 须写可检索事实（如「{角色名}的妹妹叫××」，`{角色名}`=assistant_label），禁止「表示不记得」。

### 4.4 记忆存储

- 按 `active_character` 分库：`data/memory/{角色ID}/`（含 `chroma/` 子目录）
- 每轮结束 `after_conversation_turn`：写 `[dialogue]` + 可选 fact/event 提取
- **主动搭话**（空闲/问候/日程）：同样写 `[dialogue]`，用户侧 `空闲搭话·…` / `日程提醒·…`，`skip_extraction=True`
- 入库前 `strip_expression_tags`；非中文角色记忆优先【中文】块（`memory_text_for_reply`）
- 退出桌宠 `on_shutdown` → `flush_all_session_writes` 写会话日记

### 4.6 双语输出（非中文角色）

- 模块：`pnn/pet/bilingual_reply.py`、`pnn/pet/reply_text.py`、`pnn/pet/chinese_display.py`
- 模型输出：日语朗读段 + 换行 `【中文】` 简体块
- TTS 只读日语段；气泡/终端/记忆用中文；假名漏写由 `polish_chinese_display` 词表+翻译兜底

### 4.7 NSFW 本地 Qwen

- 配置：`llm.json` → `nsfw_enabled`；权重在 `models/Qwen3.6-35B-A3B-Uncensored/`
- 路由：`pnn/llm/routing.py` — 纯闲聊走本地，Agent/MCP/识图仍走 DeepSeek
- lite 模式：`local_chat_lite` — 短 prompt、少历史；主动搭话在 NSFW 下多数仍禁用（日程除外）

### 4.5 提取器

- `pnn/memory/extractor.py`：后台 JSON，**不面向用户**
- `EXTRACT_SYSTEM` 中 `chat_summary` 用中文一句概括，禁止抄录对话原文

---

## 5. MCP / Agent 路由

**原则：MCP 开着 ≠ 每条消息都走 Agent。**

```python
from pnn.agent.routing import needs_mcp_agent
# 或 llm_service.should_use_agent_for_request(...)
```

走 Agent 的条件（任一）：

- 附图 / 截图分析
- 截图寻图下载任务
- 改代码类任务
- 明确网页浏览/下载（URL、打开网站、Playwright 等）

**不走 Agent**：纯闲聊、问角色设定、问「妹妹叫什么」「什么时候说的」等。

`server/routes/chat.py` 在流式入口用 `should_use_agent_for_request()` 分支，闲聊走 `stream_complete`。

### 5.1 提示词安全

- 含字面量 `{网站}`、`{文件名}` 等占位符的模板 **禁止**对整段 `.format()`；
- 用 `build_*_section(report_step)` 拼接，或只 format 已知 key。

---

## 6. 截图 / 识图流程

1. 附截图 → 气泡先显示固定中文提示（`get_screenshot_hint` 的 display）
2. DashScope 识图 → 摘要 TTS（日语角色：中文摘要 → `chinese_to_japanese` → `text_lang=ja`）
3. 播放时气泡 **逐句** 显示对应中文摘要（`format_analysis_segments`）
4. 发送聊天时附带 `image_analysis`，可走 Agent 下载

问候/截图提示缓存：`data/assets/time_greetings/{角色ID}/`、`data/assets/screenshot_hints/{角色ID}/`；TTS 参考音与 prompt：`data/tts/{角色ID}/`。迁移脚本：`scripts/migrate_tts_by_character.py`；预生成问候：`scripts/build_time_greetings.py`。

---

## 7. API 版本与启动

### 7.1 流式/API 版本号

修改对话逻辑、记忆注入、Agent 行为后 **必须递增**：

| 文件 | 常量 |
|------|------|
| `server/routes/chat.py` | `STREAM_SSE_VERSION` |
| `pnn/core/api_health.py` | `MIN_STREAM_SSE_VERSION`（与上一致） |
| `scripts/launcher.py` | `REQUIRED_STREAM_SSE_VERSION` |

`is_api_operational()` 检查 `stream_sse_version >= MIN`；过旧则 `ensure_api_operational()` 杀进程重启。

### 7.2 启动路径

- `launch/start_pet.bat` → 优先 `run_pet.py`（内含 API 版本检查）
- API 子进程必须用 **conda `AI` 的 python**（含 `mcp` 等依赖）
- `[FAST] API 端口已占用` 不代表代码已更新，仍可能触发重启

---

## 8. 桌宠 Controller 约定

文件：`pnn/pet/controller.py`

| 机制 | 说明 |
|------|------|
| `_turn_id` | 每轮用户发送 +1；worker 回调先比对，过期则丢弃并释放 TTS 状态 |
| `_seg_seen` / `MAX_TTS_SEGMENTS` | 分句去重，单轮最多 12 段 |
| `MAX_TTS_SYNTH_PARALLEL = 2` | 并行合成上限 |
| `_memory_turn_lock` | 记忆写入串行，防线程堆积 |
| `_bubble_translate_seq` | 分句气泡翻译序号；递增可作废未完成的整段/过期翻译回调 |
| `_voice_output_enabled` | 为 True 时气泡只跟读，禁止流式/整段全文 |
| QThread | `finished → deleteLater`；用 `_qthread_running()` 判存活 |

信号：`bubble_changed` 是 AI 气泡**唯一出口**（`app.py` → `BubbleWindow`）。

---

## 9. 配置与持久化

| 配置 | 路径 |
|------|------|
| LLM | `data/config/llm.json` |
| TTS 全局 | `data/config/tts.json`（运行时；保存时写回当前角色包 `tts` 段） |
| TTS 按角色 | `data/tts/{角色ID}/reference.wav`、`prompt.txt`、`output/`；权重 `models/character/{角色ID}/{角色ID}.ckpt|.pth` |
| 桌宠 UI | `data/config/pet_ui.json`（保存时 merge，勿整文件覆盖丢字段） |
| 记忆引擎 | `data/config/memory.json` |
| 角色包 | `data/characters/{id}/pack.json` |
| 翻译 | `data/config/translate.json` |

**角色 vs 模型目录**：`live2d/塞拉/pink_devil` 是资源路径；人设、`reply_language`、记忆核心在 **pack.json**。

### Live2D 待机动作

| 机制 | 文件 | 说明 |
|------|------|------|
| 持续微晃 | `live2d_widget._apply_idle_motion` | 正弦驱动 `ParamBodyAngle*`，幅度由 `pet_ui.json` 的 `idle_motion_amplitude` 控制 |
| 随机关键帧 | `idle_gestures.py` + `model_params.py` | 约 14–26s 随机：`lean_forward` / `body_sway` / `chest_bounce` 等；按 **cdi3** 探测胸口参数名，无则跳过 |
| 模型 .motion3 | `live2d_widget._on_idle_motion` | 约 2–3.5 分钟播放 `Idle` 组；目录内 `*.motion3.json` 自动加载 |
| 对话句动作 | `actions.py` + LLM `【动作:名称】` | 点头/摇头等，与待机池独立 |

换角色包后 `reload_model` 会重新探测参数；终端会打印 `待机随机动作: …`。

---

## 10. 新增功能时的自检清单

### 涉及语音

- [ ] 是否读取 `active_reply_language()`？
- [ ] `synthesize_tts(..., text_lang=...)` 是否传入？
- [ ] 日语角色中文文案是否 `tts_text_for_reply` / `chinese_to_japanese`？
- [ ] 长句是否分句？GBK 是否 sanitize？

### 涉及气泡

- [ ] 是否 `bubble_text_for_reply()`？
- [ ] 开语音时是否**仅**在 `_show_segment_bubble` / 带 `bubble_seq` 的翻译回调里更新？
- [ ] 开语音时 `_on_chat_delta` / `_on_chat_done` 是否避免整段 `bubble_changed`？
- [ ] `_play_audio` 开语音时是否跳过刷气泡？
- [ ] 是否与播放同步（非合成阶段）？
- [ ] 非中文角色是否需要百度翻译显示？

### 涉及 LLM

- [ ] system 是否含语言规则 + 记忆使用规则？
- [ ] 是否需要 Agent？是否走 `needs_mcp_agent`？
- [ ] 改 server 逻辑后是否 bump `STREAM_SSE_VERSION`？

### 涉及记忆

- [ ] 用户侧是否零感知（无元叙述、无摘要口吻）？
- [ ] 提取/合并是否仅后台？

---

## 11. 测试

- 单元测试放 `test/unit/`，命名 `test_<模块>.py`
- 语言/气泡：`test/unit/test_reply_text.py`
- 记忆检索/入库：`test/unit/test_memory_search.py`
- Agent 路由：`test/unit/test_agent_routing.py`

---

## 12. 常见错误（避免再犯）

| 现象 | 根因 | 正确做法 |
|------|------|----------|
| 日语角色 TTS 读中文 | 未传 `text_lang` 或未译日 | `tts_text_for_reply` + `text_lang=ja` |
| 气泡出现「记忆里」「记性」 | 未过滤整句 | `bubble_text_for_reply` |
| 问妹妹却答不记得 | Chroma 误检索 + 假遗忘摘要入库 | 混合检索 §4.2；提取器禁否定句 |
| 闲聊去搜网站 | MCP 全开时一律 Agent | `needs_mcp_agent` 条件路由 |
| 改代码不生效 | FAST 路径未重启 API | bump 版本 + `ensure_api_operational` |
| `KeyError: '网站'` | 对含 `{}` 的模板 `.format()` | 函数拼接 |
| TTS 400 GBK | 日文 `〜` U+301C | `sanitize_for_gbk_tts` |
| 同一轮语音播两遍 | 过期 turn 未释放 busy / 分句重复 | 检查 `_turn_id`、`_seg_seen` |

---

## 13. 参考文件（实现样板）

| 场景 | 参考 |
|------|------|
| 三通道文案 | `pnn/pet/reply_text.py` |
| 气泡/语音编排 | `pnn/pet/controller.py` → `_on_chat_delta` / `_on_chat_done` / `_show_segment_bubble` / `_play_audio` |
| 语言配置 | `pnn/characters/reply_lang.py` |
| 截图分句 TTS | `pnn/pet/screenshot_hint.py` → `format_analysis_segments` |
| 时段问候 | `pnn/pet/time_greeting.py` |
| 记忆 | `pnn/memory/retrieval.py`、`pnn/memory/service.py` |
| Agent 路由 | `pnn/agent/routing.py` |
| API 健康 | `pnn/core/api_health.py` |

---

*最后更新：2026-06-03 — 含 reply_language 三通道、记忆气泡过滤、语音模式逐句跟读（禁整段闪现）、MCP 条件路由、API 版本机制。*
