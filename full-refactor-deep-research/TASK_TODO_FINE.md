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
- Project Modules: runtime；source-aware tooling；service / persistence orchestration
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Current Phase Inputs:
  - Phase 1 提交：`0c5fa63`、`efc6693`、`c3ccdf2`
  - Task 4 提交：`a6e6438 feat(research): add deep agents runtime skeleton`
  - Task 5 已完成并待本次提交：research tool registry / research tools / source bundle / finalizer
  - 当前 runtime 已固定：`create_deep_agent` 单入口、`subgraphs=True`、`version="v2"`、CompositeBackend 路由
- Active Execution Wave: Task 5 已完成；下一任务 = Task 6 service/persistence orchestration
- Phase Goal: 完成 Task 6（研究会话编排与持久化服务）
- Phase Scope:
  - 包含：event store、artifact store、ResearchService、Task 6 测试
  - 不包含：Task 7+ API / SSE / frontend
- Non-goals:
  - 不恢复旧 `/api/v1/research/runs*`
  - 不在此轮接通 worker / frontend

## Part 1: 当前阶段需求与范围
### 1.1 Task 5 收口结果
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

### 1.2 固化 Task 6 可执行目标
- [ ] Task: 只实现 `tasks.md` Task 6 所需的 event store、artifact store、ResearchService、定向测试
- Goal: 让下一轮改动聚焦服务层，不抢跑 API / SSE / worker
- Inputs / Dependencies:
  - `backend/src/app/models/research_session.py`
  - `backend/src/app/models/research_event.py`
  - `backend/src/app/models/research_artifact.py`
  - `backend/src/app/services/research_planner.py`
  - `backend/src/app/services/deep_research_runtime.py`
  - `backend/src/app/services/research_finalizer.py`
- Output / Artifact: Task 6 目标声明
- Done when: 不需要再解释“下一轮具体做什么”
- Verification: medium todo / state / tasks.md 语义一致
- Notes: 默认 hard cut，不保留旧 research service

## Part 2: 当前阶段研究与拆解
### 2.1 详细检查 Task 6 相关上下文
- [ ] Task: 读取模型、runtime、planner、finalizer 与现有 service 模式
- Goal: 明确 store/service 边界、状态迁移点与工件写入时机
- Inputs / Dependencies: Phase 1 + Task 4 + Task 5 输出
- Output / Artifact: Task 6 上下文图
- Done when: 已明确 planner -> runtime -> finalizer -> artifacts 的拼装点
- Verification: state / todo 对 Task 6 的描述一致
- Notes: 事实源仍以当前代码和已验证测试为准

### 2.2 把 Task 6 拆为可执行单元
- [ ] Task: 拆成“红测 -> event store -> artifact store -> ResearchService -> 绿测 -> 提交”
- Goal: 保持一步一验
- Inputs / Dependencies: TDD 规则、Task 6 验收
- Output / Artifact: Task 6 子步骤清单
- Done when: 每个子步骤都可单独打勾
- Verification: 无含糊的“大概完成”
- Notes: 下一波先做 3.1

## Part 3: 当前阶段执行
### 3.1 新增 Task 6 回归测试（RED）
- [ ] Task: 新建 `backend/tests/research/test_research_service.py`
- Goal: 先固定服务层合同
- Inputs / Dependencies: Task 6 验收、现有 planner/runtime/finalizer
- Procedure / Implementation notes:
  - 覆盖 create session 后的状态迁移
  - 覆盖 event append 顺序
  - 覆盖 artifacts 写入 `plan_snapshot` / `report_json` / `report_md`
  - 覆盖 resume / idempotency skeleton
- Output / Artifact: failing test
- Done when: pytest 因缺失服务层实现而稳定失败
- Verification: `uv run pytest tests/research/test_research_service.py -q`
- Notes: 红阶段不能提前写 service

### 3.2 落地 Task 6 service/store skeleton（GREEN）
- [ ] Task: 实现 `ResearchEventStore`、`ResearchArtifactStore`、`ResearchService`
- Goal: 串起 planner -> runtime -> finalizer
- Inputs / Dependencies: failing test、三表模型、runtime/source bundle/finalizer
- Output / Artifact: service/store 文件
- Done when: 测试转绿
- Verification: `uv run pytest tests/research/test_research_service.py -q`
- Notes: 发现旧 research service 遗留则直接删除

### 3.3 运行定向验证并修复
- [ ] Task: 跑 pytest / ruff / 必要的联合回归
- Goal: 获得 fresh verification
- Inputs / Dependencies: 测试文件、service/store、已有 runtime 代码
- Output / Artifact: 验证记录
- Done when: 定向 pytest / ruff 通过
- Verification:
  - `uv run pytest tests/research/test_research_service.py -q`
  - `uv run pytest tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py tests/research/test_research_source_tooling.py tests/research/test_research_service.py -q`
  - `uv run ruff check ...`
- Notes: 失败则继续留在本步骤

## Part 4: 验证与切换
### 4.1 验证本阶段已完成输出
- [ ] Task: 复核 Task 6 验收与 medium todo / state 同步
- Goal: 防止“代码过了但 planning 仍旧过时”
- Done when: todo / state / git 提交描述一致
- Verification: 手动交叉检查 planning files + git diff
- Notes: 当前仅覆盖 Task 6 切换

### 4.2 准备下一个任务
- [ ] Task: 更新 planning/state，并提交 Task 6
- Goal: 让下一轮从 Task 7 直接起步
- Done when: 下一任务与阻塞点明确
- Verification: `git status --short`
- Notes: 提交后再继续 Task 7
