# 后端审查发现

## 基线事实

- 目录：`backend/src/app`
- Python 文件数：`232`
- 顶层目录体量：
  - `services`: 62 files / 30462 lines
  - `agents`: 38 files / 16829 lines
  - `integrations`: 14 files / 3460 lines
  - `worker`: 16 files / 2563 lines
  - `api`: 23 files / 2463 lines
  - `schemas`: 16 files / 2046 lines
  - `models`: 23 files / 1875 lines
  - `core`: 14 files / 1857 lines

## FastAPI 架构符合项

- `app.main` 已使用 `lifespan`，符合当前 FastAPI 推荐方向。
- 路由通过 `api/v1/api.py` 聚合，入口层未直接写业务逻辑，整体方向正确。
- `db/session.py` 使用 `async_sessionmaker(..., expire_on_commit=False)`，符合 SQLAlchemy 2 async 基线。
- 项目整体已使用 Pydantic v2 风格配置。
- `M1` 后 `main.py` 已收敛为单一应用构建入口，启动资源编排从 transport edge 进一步下沉到 `bootstrap/`。
- `M1` 后 `chats.py` 已把 service wiring 和 heartbeat helper 从 route 主线中抽离，endpoint 只保留 HTTP 与流程主线。

## FastAPI 架构偏差项

- `backend/pyproject.toml` 固定 `fastapi>=0.128.0,<0.129`，低于 skill 参考 `0.135.x`；本次因“严禁修改当前功能”不做依赖升级，只记录为版本基线偏差。
- `services/` 目录承担了过多 orchestration、持久化拼接、格式整理与边界翻译职责，明显偏离“service focused”原则。
- 当前没有显式 `repositories/` 层；部分 service 直接承担了查询/写入与工作流编排双重职责。

## AGENTS 原则符合项

- 当前主入口和大多数模块保留了单一路径，没有明显双轨实现泛滥。
- 新近 research 相关代码已明确使用 `session_id`、`presentation_snapshot` 等收敛事实源。
- 审查目标已明确限定为“纯重构，不改功能”，与最小改动原则一致。
- `M1` 验证严格遵守了“先红后绿 + fresh startup verification”。

## AGENTS 原则风险项

- 多处仍保留“legacy/compat”语义，需逐一确认是否仍是当前事实源：
  - `schemas/knowledge_bases.py`
  - `services/ingestion_batch_service.py`
  - `services/query_rewrite_service.py`
  - `services/retrieval_service.py`
  - `services/streaming.py`
  - `agents/tools/web_search.py`
- 某些 service 既做业务编排又做输出格式兼容，违反“默认不向后兼容”的收敛倾向。
- 当前 `backend/tests` 对 research、retrieval、worker 主链路的结构保护测试仍不足，后续里程碑要继续补。

## 超大文件清单（>800 行）

- `services/kb_chat_service.py` 4983
- `services/query_rewrite_service.py` 2882
- `services/retrieval_service.py` 2872
- `services/general_chat_service.py` 2457
- `agents/kb_chat_agentic/preprocess.py` 2313
- `agents/kb_chat_agentic/answer_subgraph.py` 2025
- `agents/kb_chat_agentic/reflection.py` 1880
- `services/deep_research_runtime.py` 1801
- `services/research_service.py` 1608
- `services/ingestion_batch_service.py` 1439
- `agents/tools/web_search.py` 1339
- `agents/kb_chat_agentic_graph.py` 1304
- `agents/kb_chat_trace_display_contract.py` 1296
- `services/chunking.py` 1042
- `agents/retrieval_subgraph.py` 871
- `agents/kb_chat_trace_nodes.py` 805
- `core/settings.py` 803

## 初步冗余/遗留候选

- `services/ingestion_batch_service.py:947` 标注“向后兼容别名”；若无真实调用应移除。
- `services/query_rewrite_service.py:1894` 标注“向后兼容别名”；候选遗留代码。
- `agents/tools/web_search.py:984` 明示“兼容旧接口的别名”；候选遗留代码。
- `services/retrieval_service.py` 文档直接写明兼容 legacy callers；需收敛。
- `schemas/knowledge_bases.py` 含 legacy field 兼容逻辑；需要核实是否仍是有效事实源。
- `services/streaming.py` 含 legacy `<think>` 兼容逻辑；需要确认是否仍被当前模型链路依赖。

## 启动与运维事实

- 启动脚本：`scripts/start_all.ps1`
- 后端 API 启动命令：
  - `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop app.core.uvicorn_loop:windows_selector_loop_factory`
- Ready 探针：
  - `/api/v1/ready`
- 已知经验：
  - 启动验证前要确认 `ready=200`
  - 不要重复拉起同一套 worker 树
  - `infra/up.ps1` 在当前环境应用 PowerShell 7 解释器更稳，避免 UTF-8 误解码

## M1 详细发现

- `backend/src/app/main.py` 原先同时负责：
  - setting 读取与 logging 初始化
  - engine/sessionmaker 取得
  - schema guard
  - runtime config 初始化/关闭
  - stale agent run recovery
  - checkpoint/store 初始化/关闭
  - HTTP/Embedding/Milvus/Redis client 初始化与关闭
  - FastAPI app 构建、middleware 注册、router 注册、异常处理注册
- `backend/src/app/api/v1/endpoints/health.py` 的 `/ready` 直接依赖 `app.state.engine`、`app.state.redis`、`app.state.milvus_client`，因此 `M1` 保持了这些 state 名称和 ready 依赖语义不变。
- `backend/src/app/api/v1/endpoints/chats.py` 当前已抽取的内容：
  - `stream_heartbeat_payload`
  - `build_kb_chat_service`
  - `build_general_chat_service`
- `chats.py` 中刻意不动的内容：
  - 路由路径、response_model、status_code
  - 数据库查询条件与删除顺序
  - `ChatSessionType` 分流语义

## M1 纯重构结果

- 新增 `backend/src/app/bootstrap/app_factory.py`，把 app 构建、middleware、router、异常处理注册统一收敛。
- 新增 `backend/src/app/bootstrap/lifespan.py`，把启动/关闭顺序抽离为独立生命周期模块。
- `backend/src/app/main.py` 现在只负责 logging 初始化、settings 获取和 `create_app(settings)`。
- 新增 `backend/src/app/api/v1/endpoints/chat_dependencies.py`，把 chat service wiring 和 heartbeat helper 从 endpoint 文件抽出。
- `backend/src/app/api/v1/endpoints/chats.py` 只保留 endpoint 主线与查询/分流逻辑，未更改任何 HTTP 契约。

## M1 验证证据

- 红测：`uv run pytest tests/test_app_factory.py tests/test_chat_endpoint_dependencies.py -q` 初次失败，错误为 `ModuleNotFoundError: No module named 'app.bootstrap'` 和 `No module named 'app.api.v1.endpoints.chat_dependencies'`。
- 绿测：`uv run pytest tests/test_app_factory.py tests/test_chat_endpoint_dependencies.py -q` 通过，结果为 `4 passed`。
- 类型检查：`uv run pyright -p .` 通过，结果为 `0 errors, 0 warnings, 0 informations`。
- Lint：`uv run ruff check src/app/main.py src/app/bootstrap src/app/api/v1/endpoints/chats.py src/app/api/v1/endpoints/chat_dependencies.py tests/test_app_factory.py tests/test_chat_endpoint_dependencies.py` 通过，结果为 `All checks passed!`。
- 启动验证：先启动 infra，再以 `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop app.core.uvicorn_loop:windows_selector_loop_factory` 后台启动，`/api/v1/ready` 返回 `200`，响应体 `status=ready`，Postgres/Redis/Milvus/MinIO 均 `ok=true`。

## 里程碑设计结论

- `M1` 已验证通过，可进入 `M2`。
- Research 与 KB Chat 是两条最大的职责堆积链，分别作为 `M2` / `M3`。
- Ingestion/Worker 与 Agents/Integrations/Settings 分为 `M4` / `M5`，避免单次变更过宽。
