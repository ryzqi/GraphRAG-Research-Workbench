# Task Todo - Fine

## Project / Phase Context
- Roadmap File / Reference: `full-refactor-deep-research/PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference:
  - `full-refactor-deep-research/archive/TASK_TODO_MEDIUM.phase-1-foundation.md`
  - `full-refactor-deep-research/archive/TASK_TODO_FINE.phase-1-foundation.md`
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files:
  - `PROJECT_PHASE_ROADMAP.md`
  - `TASK_TODO_MEDIUM.md`
  - `TASK_TODO_FINE.md`
  - `PROJECT_EXECUTION_STATE.md`
- Project Modules: runtime；source-aware tooling；service / persistence orchestration；API / worker / export
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Current Phase Inputs:
  - Phase 1 提交：`0c5fa63`、`efc6693`、`c3ccdf2`
  - Task 4 提交：`a6e6438 feat(research): add deep agents runtime skeleton`
  - Task 5 提交：`dfbf457 feat(research): add source-aware research tooling`
  - Task 6 提交：`a12593e feat(research): add research service orchestration`
  - 当前 runtime 已固定：`create_deep_agent` 单入口、`subgraphs=True`、`version="v2"`、CompositeBackend 路由
- Active Execution Wave: Task 7 已完成；下一任务 = Task 8 exporter/artifact read
- Phase Goal: 完成 Task 8（导出链路与工件读取）
- Phase Scope:
  - 包含：`research_exporter.py`、`export_service.py`、export worker、按 `session_id` 读取工件
  - 不包含：Task 9+ frontend
- Non-goals:
  - 不恢复旧 `/api/v1/research/runs*`
  - 不在此轮接通 frontend workbench

## Part 1: 当前阶段需求与范围
### 1.1 Task 6 收口结果
- [x] Task: provider-specific research tools、source bundle 与 finalizer 已落地
- Goal: 为 Task 6 提供可调用的 runtime/source-aware building blocks
- Inputs / Dependencies:
  - `backend/src/app/agents/tool_calling/registry.py`
  - `backend/src/app/agents/tools/research_tools.py`
  - `backend/src/app/services/research_source_bundle.py`
  - `backend/src/app/services/research_finalizer.py`
- Output / Artifact:
  - `build_research_tool_registry`
  - `tavily_search / tavily_extract / tavily_crawl / tavily_research`
  - `searxng_search / arxiv_search / arxiv_fetch`
  - source bundle 去重与 finalizer 双产物骨架
- Verification:
  - `uv run pytest tests/research/test_research_source_tooling.py -q` -> `5 passed`
  - `uv run pytest tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py -q` -> `23 passed`
  - `uv run ruff check src/app/agents/tool_calling/registry.py src/app/agents/tools/research_tools.py src/app/agents/tools/web_search_providers/searxng_provider.py src/app/services/deep_research_runtime.py src/app/services/research_runtime_types.py src/app/services/research_source_bundle.py src/app/services/research_finalizer.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py` -> `All checks passed!`
- Notes:
  - 本轮未发现需删除的旧 research runtime 文件
  - arXiv 依赖已锁定为 `arxiv==2.4.1`
  - Task 6 已新增 `research_brief`、`interim_findings` 工件
  - Task 6 已新增 `confirm_plan` / `interrupt_session` / `resume_session`

### 1.2 固化 Task 8 可执行目标
- [x] Task: 只实现 `tasks.md` Task 8 所需的 export / artifact read contract
- Goal: 让下一轮改动聚焦导出链路，不抢跑 frontend
- Inputs / Dependencies:
  - `backend/src/app/services/research_service.py`
  - `backend/src/app/services/export_service.py`
  - `backend/src/app/worker/tasks/export.py`
  - `backend/src/app/models/research_artifact.py`
- Output / Artifact: Task 8 目标声明
- Done when: 不需要再解释“下一轮具体做什么”
- Verification: medium todo / state / tasks.md 语义一致
- Notes: 默认 hard cut，不保留旧 research service

## Part 2: 当前阶段研究与拆解
### 2.1 详细检查 Task 7 已落地上下文
- [x] Task: 读取 router、worker、schemas 与当前 service 实现
- Goal: 明确 Task 8 可直接复用的工件读取入口
- Inputs / Dependencies: Phase 1 + Task 4 + Task 5 + Task 6 + Task 7 输出
- Output / Artifact:
  - `create_session` -> `plan_snapshot` + `research_brief`
  - `confirm_plan`
  - `/api/v1/research/sessions*`
  - `stream` -> `ResearchEventEnvelope`
  - `artifacts` -> `ResearchArtifactsResponse`
- Done when: 已明确 planner -> runtime -> finalizer -> artifacts 的拼装点
- Verification: state / todo 对 Task 7 的描述一致
- Notes: 事实源仍以当前代码和已验证测试为准

### 2.2 把 Task 8 拆为可执行单元
- [x] Task: 拆成“盘点 export 读取路径 -> 红测 -> exporter/export_service/worker 改造 -> 绿测 -> 提交”
- Goal: 保持一步一验
- Inputs / Dependencies: TDD 规则、Task 8 验收
- Output / Artifact: Task 8 子步骤清单
- Done when: 每个子步骤都可单独打勾
- Verification: 无含糊的“大概完成”
- Notes: 下一波先做 3.1

## Part 3: 当前阶段执行
### 3.1 Task 7 回归测试（RED -> GREEN）完成记录
- [x] Task: 已新增 `backend/tests/api/test_research_endpoints.py`
- Goal: 先固定当前 research API / worker 契约
- Inputs / Dependencies: Task 7 验收、现有 service / schema
- Procedure / Implementation notes:
  - 覆盖 route set
  - 覆盖 create / confirm-plan / stream / interrupt / resume / artifacts
  - 覆盖 `Last-Event-ID` 恢复过滤
- Output / Artifact: failing test -> passing test
- Done when: pytest 因 `/api/v1/research/*` 当前端点集合缺失而失败，随后转绿
- Verification: `uv run pytest tests/api/test_research_endpoints.py -q`
- Notes: 红阶段不能提前写 router / worker

### 3.2 落地 Task 7 API / worker 集成（GREEN）
- [x] Task: 已实现 `research.py` router、`api.py` 接线、worker `research.py`
- Goal: 将 research 会话契约接回当前公开入口
- Inputs / Dependencies: failing test、Task 6 service、research schemas
- Output / Artifact:
  - `backend/src/app/api/v1/endpoints/research.py`
  - `backend/src/app/api/v1/api.py`
  - `backend/src/app/worker/tasks/research.py`
  - `backend/src/app/worker/celery_app.py`
  - `backend/src/app/schemas/research.py`
- Done when: 测试转绿
- Verification: `uv run pytest tests/api/test_research_endpoints.py -q`
- Notes:
  - stream 统一输出 `ResearchEventEnvelope`
  - worker 只通过 `ResearchService` 读取 session / plan snapshot / execute_session

### 3.3 运行定向验证并修复
- [x] Task: 跑 pytest / ruff / 必要的联合回归
- Goal: 获得 fresh verification
- Inputs / Dependencies: 测试文件、service/store、已有 runtime 代码
- Output / Artifact:
  - `uv run pytest tests/api/test_research_endpoints.py -q` -> `3 passed`
  - `uv run pytest tests/api/test_research_endpoints.py tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py tests/research/test_research_service.py -q` -> `31 passed`
  - `uv run ruff check src/app/api/v1/api.py src/app/api/v1/endpoints/research.py src/app/schemas/research.py src/app/services/research_service.py src/app/worker/celery_app.py src/app/worker/tasks/research.py tests/api/test_research_endpoints.py` -> `All checks passed!`
- Done when: 定向 pytest / ruff 通过
- Verification:
  - `uv run pytest tests/research/test_research_service.py -q`
  - `uv run pytest tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py tests/research/test_research_service.py -q`
  - `uv run ruff check ...`
- Notes: 失败则继续留在本步骤

## Part 4: 验证与切换
### 4.1 验证本阶段已完成输出
- [x] Task: 复核 Task 7 验收与 medium todo / state 同步
- Goal: 防止“代码过了但 planning 仍旧过时”
- Done when: todo / state / git 提交描述一致
- Verification: 手动交叉检查 planning files + git diff
- Notes: 当前仅覆盖 Task 7 切换

### 4.2 准备下一个任务
- [ ] Task: 更新 planning/state，并提交 Task 7
- Goal: 让下一轮从 Task 8 直接起步
- Done when: 下一任务与阻塞点明确
- Verification:
  - `git status --short`
  - Task 7 提交记录
- Notes: 提交后再继续 Task 8
