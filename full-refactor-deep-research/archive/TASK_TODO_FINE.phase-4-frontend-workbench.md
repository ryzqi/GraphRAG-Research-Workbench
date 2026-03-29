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
- Project Modules: runtime；source-aware tooling；service / persistence orchestration；API / worker / export；frontend data layer / workbench
- Current Phase: Phase 4 - 前端研究工作台 hard cut
- Current Phase Inputs:
  - Phase 1 提交：`0c5fa63`、`efc6693`、`c3ccdf2`
  - Task 4 提交：`a6e6438 feat(research): add deep agents runtime skeleton`
  - Task 5 提交：`dfbf457 feat(research): add source-aware research tooling`
  - Task 6 提交：`a12593e feat(research): add research service orchestration`
  - Task 7 提交：`13d700f feat(research): add current research session endpoints`
  - Task 8 提交：`f290489 feat(research): add research artifact exports`
  - Task 9 提交：`5f429ee feat(research): cut frontend to session contract`
  - 当前 runtime 已固定：`create_deep_agent` 单入口、`subgraphs=True`、`version="v2"`、CompositeBackend 路由
- Active Execution Wave: Task 9 已完成；下一任务 = Task 10 research workbench
- Phase Goal: 完成 Task 10（前端事件驱动研究工作台）
- Phase Scope:
  - 包含：`ResearchPage`、timeline / plan preview / interrupt / artifact 面板
  - 不包含：Task 11+ observability / eval / gate
- Non-goals:
  - 不恢复旧 `/api/v1/research/runs*`
  - 不在此轮接通 Task 11+ 门禁

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

### 1.2 固化 Task 10 可执行目标
- [x] Task: 只实现 `tasks.md` Task 10 所需的前端 workbench 集成
- Goal: 让下一轮改动聚焦计划展示、timeline、中断与工件面板，不扩散到 observability gate
- Inputs / Dependencies:
  - `frontend/src/views/ResearchPage.tsx`
  - `frontend/src/hooks/queries/useResearch.ts`
  - `frontend/src/types/researchEvents.ts`
  - `backend/src/app/api/v1/endpoints/research.py`
  - `backend/src/app/schemas/research.py`
  - `backend/src/app/api/sse.py`
- Output / Artifact: Task 10 目标声明
- Done when: 不需要再解释“下一轮具体做什么”
- Verification: medium todo / state / tasks.md 语义一致
- Notes: 默认 hard cut，不保留旧 research service

## Part 2: 当前阶段研究与拆解
### 2.1 详细检查 Task 9 已落地上下文
- [x] Task: 读取 `research.ts`、`researchEvents.ts`、`useResearch.ts`、`ResearchPage.tsx` 与 `exports.ts`
- Goal: 明确 Task 10 可直接复用的数据层、续流策略与工件入口
- Inputs / Dependencies: Phase 1 + Task 4 + Task 5 + Task 6 + Task 7 + Task 8 + Task 9 输出
- Output / Artifact:
  - `ResearchEventEnvelope`
  - `ResearchArtifactsResponse`
  - `mergeResearchEventEnvelopes`
  - `Last-Event-ID` + `resume_from_event_id` 续流策略
  - research export `session_id`
- Done when: 已明确 plan -> session -> stream -> artifact -> export 的前端拼装点
- Verification: state / todo 对 Task 9 的描述一致
- Notes: 事实源仍以当前代码和已验证测试为准

### 2.2 把 Task 10 拆为可执行单元
- [x] Task: 拆成“盘点 workbench 组件边界 -> 红测/type-level 基线 -> page/components 集成 -> 绿测 -> 提交”
- Goal: 保持一步一验
- Inputs / Dependencies: TDD 规则、Task 10 验收
- Output / Artifact: Task 10 子步骤清单
- Done when: 每个子步骤都可单独打勾
- Verification: 无含糊的“大概完成”
- Notes: 下一波先做 3.1

## Part 3: 当前阶段执行
### 3.1 Task 9 回归测试（RED -> GREEN）完成记录
- [x] Task: 已新增 `frontend/src/services/research.test.ts`，并扩展 `frontend/src/services/exports.test.ts`
- Goal: 先固定 session-based research service / event merge / export request 契约
- Inputs / Dependencies: Task 9 验收、当前 session API / artifacts / export 契约
- Procedure / Implementation notes:
  - 覆盖 create / confirm / artifacts 当前端点
  - 覆盖 `mergeResearchEventEnvelopes`
  - 覆盖 `Last-Event-ID` 优先 + `resume_from_event_id` fallback query
  - 覆盖 research export `session_id`
- Output / Artifact: failing test -> passing test
- Done when: Vitest 因 `frontend/src/types/researchEvents.ts` 缺失而失败，随后转绿
- Verification: `npx vitest run src/services/research.test.ts src/services/exports.test.ts`
- Notes: 红阶段不能继续沿用旧 `/api/v1/research/runs*`

### 3.2 落地 Task 9 frontend data layer hard cut（GREEN）
- [x] Task: 已实现 `research.ts`、`researchEvents.ts`、`useResearch.ts`、`ResearchPage.tsx` 与 `exports.ts` 改造
- Goal: 将前端研究服务切到 `session_id` 驱动的 current session contract
- Inputs / Dependencies: failing test、Task 7 API / artifacts 契约、Task 8 export 契约
- Output / Artifact:
-  - `frontend/src/services/research.ts`
-  - `frontend/src/types/researchEvents.ts`
-  - `frontend/src/hooks/queries/useResearch.ts`
-  - `frontend/src/views/ResearchPage.tsx`
-  - `frontend/src/services/exports.ts`
- Done when: 测试转绿
- Verification: `npx vitest run src/services/research.test.ts src/services/exports.test.ts`
- Notes:
  - 前端 research service 统一走 `/api/v1/research/sessions*`
  - 统一流消费器按 `event_id` 去重、按 `sequence` 重排
  - 续流优先 `Last-Event-ID`，失败后回退 artifacts 快照 + 增量流
  - 已删除旧 run-centric ResearchPage 沉淀入口

### 3.3 运行定向验证并修复
- [x] Task: 跑 Vitest / typecheck / services 回归
- Goal: 获得 fresh verification
- Inputs / Dependencies: 测试文件、service/types/hooks/page、已有 session API / artifacts 契约
- Output / Artifact:
-  - `npx vitest run src/services/research.test.ts src/services/exports.test.ts` -> `8 passed`
-  - `npx vitest run src/services` -> `78 passed`
-  - `npm run typecheck` -> `passed`
- Done when: 定向 Vitest / typecheck 通过
- Verification:
-  - `npx vitest run src/services/research.test.ts src/services/exports.test.ts`
-  - `npx vitest run src/services`
-  - `npm run typecheck`
- Notes: 失败则继续留在本步骤

## Part 4: 验证与切换
### 4.1 验证本阶段已完成输出
- [x] Task: 复核 Task 9 验收与 medium todo / state 同步
- Goal: 防止“代码过了但 planning 仍旧过时”
- Done when: todo / state / git 提交描述一致
- Verification: 手动交叉检查 planning files + git diff
- Notes: 当前仅覆盖 Task 9 切换

### 4.2 准备下一个任务
- [x] Task: 更新 planning/state，并提交 Task 9
- Goal: 让下一轮从 Task 10 直接起步
- Done when: 下一任务与阻塞点明确
- Verification:
  - `git status --short`
  - Task 9 提交记录：`feat(research): cut frontend to session contract`
- Notes: 下一步进入 Task 10 workbench 组件边界盘点与红测基线
