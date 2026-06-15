# Python 改代码 Skill

仓库：<https://github.com/chisworld/private_robot>

适用：桌宠 Agent + filesystem MCP 修改本项目 Python 代码。

## 标准流程

1. **定位**：`search_files` 或 `list_directory`，确认路径存在（如 `pnn/...`、`server/...`）。
2. **阅读**：`read_text_file` 读目标函数/类所在段落；文件 >200 行时只读相关区段（用 offset/limit 若工具支持）。
3. **修改**：优先 `edit_file`（old_string 须与磁盘完全一致，含缩进）；仅新建小文件或整文件重写时用 `write_file`。
4. **核对**：改后再 `read_text_file` 看 diff 附近几行是否正确。
5. **汇报**：列出改动文件、函数名、行为变化；不要贴整文件。

## 禁止

- 读/写 `.env`、含 `api_key`/`secret` 的配置
- 修改 `models/` 下模型权重
- 执行 Shell、pip、pytest
- 一次任务改超过 3 个文件（除非用户明确要求）

## 常见目录

| 路径 | 用途 |
|------|------|
| `pnn/pet/` | 桌宠 UI、控制器 |
| `pnn/agent/` | Agent 编排 |
| `pnn/mcp/` | MCP 服务 |
| `pnn/llm/` | 对话 LLM |
| `server/` | FastAPI |
| `data/config/` | 运行时 JSON 配置 |

## 提问不够具体时

先回复：需要改哪个文件、哪段逻辑，请用户补充；不要猜路径乱改。
