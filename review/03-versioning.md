# Review 03 - 依赖版本与“最新版本”匹配

变更：`openspec/changes/refactor-kb-agent-orchestration`  
日期：2026-01-25

## 结论
**⚠️ 后端依赖整体“接近最新”但落后 0-1 个 patch；前端 React/Vite 落后一个大版本级别。**  
代码用法总体符合当前锁定版本（LangGraph/LangChain/MCP/FastAPI 的主 API 用法合理），但如果要满足“严格最新”，需要升级依赖并做回归验证。

## 后端（Python）
| 组件 | 当前锁定/使用 | 最新（截至 2026-01-25） | 备注 |
|---|---:|---:|---|
| fastapi | 0.127.0（`backend/uv.lock`） | 0.128.0 | 落后 1 个 patch |
| langgraph | 1.0.6（`backend/pyproject.toml`） | 1.0.7 | 落后 1 个 patch |
| langchain | 1.2.6（`backend/pyproject.toml`） | 1.2.7 | 落后 1 个 patch |
| langchain-openai | 1.1.6（`backend/uv.lock`） | 1.1.7 | 落后 1 个 patch |
| langchain-mcp-adapters | 0.2.1（`backend/uv.lock`） | 0.2.1 | 已是最新 |

### API 用法匹配检查（要点）
- ✅ 工具导入遵循项目约束（从 `langchain.tools` 引入）：`backend/src/app/agents/tool_calling/registry.py:14`
- ✅ LangGraph `StateGraph/compile/astream/checkpointer/store` 的用法符合 1.x：`backend/src/app/services/kb_chat_service.py:593`
- ⚠️ LangGraph Store 的具体 import 路径需与 1.0.x 文档核对（不同版本可能有路径迁移）；建议升级时重点回归 `store/checkpointer` 的初始化与线程恢复逻辑。
- ⚠️ MCP adapter API（`MultiServerMCPClient`、`tool_interceptors`、`MCPToolCallRequest`）在升级时需要核对签名是否变更：`backend/src/app/integrations/mcp_adapters.py:15`

## 前端（Node）
| 组件 | 当前 | 最新（截至 2026-01-25） | 备注 |
|---|---:|---:|---|
| react | ^18.3.1 | 19.0.0 | 大版本差异，升级成本较高 |
| vite | ^5.4.11 | 7.0.6 | 大版本差异，可能涉及构建/插件变更 |

## 建议
1) 后端：若追求“严格最新”，优先升级 patch（fastapi/langgraph/langchain/langchain-openai）并跑最小回归（KB chat streaming、checkpoint/store、检索与 rerank）。
2) 前端：React/Vite 属于大版本升级，建议单独开提案/任务，避免与本次编排重构耦合。

