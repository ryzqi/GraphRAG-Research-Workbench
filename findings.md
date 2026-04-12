# Backend 清理发现记录

## 基线

- 范围事实源：`git ls-files backend`
- 当前统计：
  - `backend/src`: 336 个文件
  - `backend/tests`: 24 个文件
  - `backend/alembic`: 16 个文件
  - 根文件：`backend/pyproject.toml`、`backend/alembic.ini`
- 当前分支基线：待切出专用清理分支

## 高风险动态/注册点

- `backend/src/app/api/v1/api.py`
  - FastAPI 路由统一注册点；删 endpoint 前必须确认未在此处 `include_router`
- `backend/src/app/worker/celery_app.py`
  - Celery `include` 列表是 worker 任务注册点；删 task 模块前必须先核查此处
- `backend/src/app/bootstrap/lifespan.py`
  - 应用启动和关闭边界；初始化项不可凭“暂时没看到引用”删除
- `backend/src/app/prompts/loader.py`
  - 提示词模板加载边界；模板 YAML 是否冗余不能只看 Python 静态引用
- `backend/src/app/integrations/mcp_adapters.py`
  - 可能存在字符串驱动适配关系；删除前要核查配置与调用方
- `backend/src/app/integrations/model_runtime_config.py`
  - 运行时模型配置入口；与 provider、health probe、factory 互相耦合
- `backend/src/app/services/research_runtime_factory.py`
  - Deep research backend 路由与工具装配边界

## 大文件热点

- `backend/src/app/agents/kb_chat_agentic/preprocess.py` 2107 行
- `backend/src/app/agents/kb_chat_agentic/answer_subgraph.py` 1876 行
- `backend/src/app/agents/kb_chat_agentic/reflection.py` 1725 行
- `backend/src/app/services/general_chat_service_execution.py` 1194 行
- `backend/src/app/services/chunking.py` 900 行
- `backend/src/app/agents/retrieval_subgraph.py` 794 行
- `backend/src/app/services/query_rewrite_planning_ops.py` 768 行
- `backend/src/app/services/research_service.py` 735 行
- `backend/src/app/core/settings.py` 720 行
- `backend/src/app/services/kb_chat_service_stream_protocol.py` 718 行

## 当前策略

- 先判“是否真无用”，再决定“删还是保留”。
- 对大文件，优先找：
  - 已废弃 helper
  - 重复 contract / serializer / mapper
  - 仅为历史兼容保留的分支
  - 已拆模块后残留的桥接函数
- 对 `alembic/versions`，默认高度保守：
  - 没有清晰迁移链路证据，不做删除
- 对 `prompts/templates`，默认先做“加载路径核查”，不是先删 YAML
- 对 `tests`，既是行为基线，也是“遗留测试是否仍对应现存行为”的审查对象

## 已确认候选

- `backend/src/app/services/kb_chat_live_artifacts.py`
  - 状态：已确认可删
  - 证据：
    - 仓内 `rg -n "kb_chat_live_artifacts|parse_sse_text|render_case_markdown|ParsedSseEvent|_parse_sse_block" .\backend\src .\backend\tests` 仅命中该文件自身
    - 代码库检索未发现 Python 导入、测试引用、包导出或运行时反射路径
  - 处理：
    - 作为首个低风险清理点直接删除

- `backend/src/app/services/research_service.py`
  - 状态：已清理零引用私有 helper
  - 处理：
    - 删除 `_json_mapping_payload`
    - 删除 `_runtime_live_board_updated_at`
    - 删除 `_read_json_artifact`

- `backend/src/app/services/research_presentation_snapshot.py`
  - 状态：已清理零引用 helper
  - 处理：
    - 删除 `_read_artifact_array`

- `backend/src/app/services/research_workspace_files.py`
  - 状态：已清理零引用常量
  - 处理：
    - 删除 `RESEARCH_BOOTSTRAP_ARTIFACT_KEYS`

- `backend/src/app/core/tracing.py` / `backend/src/app/core/security.py`
  - 状态：已确认并删除
  - 证据：
    - 仓内全文检索仅命中模块自身、`settings.py` 与 `pyproject.toml`
    - 无 FastAPI、Celery、provider、router、test、字符串装配消费者
  - 处理：
    - 删除两个孤儿模块
    - 同步删除 `Settings` 中对应的 `JWT_*` 与 `OTEL_*` 字段
    - 同步删除 `backend/pyproject.toml` 中 `pyjwt`、`opentelemetry-api`
    - 通过 `uv lock` 同步 `backend/uv.lock`

- `backend/src/app/agents/base.py` / `backend/src/app/agents/tool_calling/builder.py`
  - 状态：已确认并删除
  - 证据：
    - 仓内静态检索无消费者
  - 处理：
    - 删除未消费基类模块
    - 删除未消费 `ToolCallingGraphBuilder`
    - 清理 `tool_calling/__init__.py` 的无用导出

- `backend/src/app/agents/answer_subgraph.py`
  - 状态：已删除单层桥接
  - 处理：
    - `kb_chat_agentic_graph.py` 改为直接导入 `kb_chat_agentic.answer_subgraph`

- `backend/src/app/services/research_planner_types.py`
  - 状态：已清理未消费字段
  - 处理：
    - 删除 `ResearchPlannerResult.auto_approve`
    - 同步删除 planner / test 构造参数

- `backend/src/app/services/research_runtime_factory.py`
  - 状态：已清理未调用方法
  - 处理：
    - 删除 `DeepResearchRuntime.stream_kwargs()`

- `backend/src/app/services/research_runtime_types.py`
  - 状态：已清理未消费类型槽位
  - 处理：
    - 删除 `ResearchProviderId`
    - 删除 `DEFAULT_RESEARCH_PROVIDER_IDS`
    - 删除 `ResearchRuntimeConfig.provider_ids`
    - 删除 `ResearchBackendPolicy.ephemeral_roots`
    - 删除 `ResearchBackendPolicy.persistent_roots`

## 明确保留项

- `research_service_execution.py` 中 `report_json` 的 verification 镜像 artifacts
  - 原因：仍涉及 finalizer/session ops 契约面，静态证据不足以证明删除安全
- `search/web/retrievers/tavily.py` 与 `search/web/retrievers/searxng.py`
  - 原因：虽然实现很薄，但仍被测试和包导出锁定，当前收益过低
- `KbChatAgenticGraph.__init__` 的兼容参数
  - 原因：属于构造签名面，删除收益小，潜在外部调用风险高
- 若干 research 扩展槽位与弱测试
  - 原因：当前更适合后续有更强行为证据时再单独清理

## 来自记忆的协作偏好

- 用户从“审查冗余”进入“开始清理”时，可直接执行，不需要额外规划回合。
- 完成判据必须是 direct verification，不能只凭分析声称清理完成。
