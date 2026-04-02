# Task Todo - Fine

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference: None
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: Backend Research Session Contract / Frontend Research Surface / Runtime Rendering
- Brownfield Context / Codebase Map: `backend/src/app/models/research_session.py`, `backend/src/app/schemas/research.py`, `backend/src/app/services/research_service.py`, `backend/src/app/api/v1/endpoints/research.py`, `backend/src/app/worker/tasks/research.py`, `frontend/src/types/researchEvents.ts`, `frontend/src/services/research.ts`, `frontend/src/hooks/queries/useResearch.ts`, `frontend/src/views/ResearchPage.tsx`, `frontend/src/components/research/*`, `frontend/src/components/chat/MarkdownContent.tsx`
- Primary User / Stakeholder: 深度研究页面用户
- Customer Problem / Desired Outcome: 用户需要在右侧单画布里先确认计划，再显式开始执行，最终直接看到支持 Mermaid 的 Markdown 回答
- Why Now / Decision Driver: 当前自动开始执行与分裂布局不满足最新产品目标
- Phase Roadmap Summary: 先红灯锁合同，再实现主流程，再做渲染与验证收口
- Current Phase: Phase 1 - 合同与测试先行
- Current Phase Inputs: 已批准实施方案；现有 clarify/scoper/runtime 链路；已有前端/后端测试基座
- Active Execution Wave: 已完成
- Phase Goal: 让新流程缺口以稳定失败测试呈现
- Phase Scope: 测试与执行工件
- Non-goals: 本阶段不写生产实现
- Phase Deliverables: 失败测试与红灯验证证据
- Entry Criteria: 用户已要求实现计划
- Phase Exit Criteria: create/clarification/replan/start/stop + single-canvas + Mermaid 目标均被测试锁定
- Next Phase Trigger / Transition Notes: 红灯稳定后开始实现
- Previous Phase Summary: None

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: Rewrite the approved current-phase request into a directly executable objective
- Goal: Remove ambiguity before the active phase begins
- Inputs / Dependencies: 批准方案、现有 research 代码结构
- Procedure / Implementation notes: 用“显式开始 + 单画布 + Mermaid + stop hard cut”定义红灯范围
- Output / Artifact: 本 fine todo 上下文
- Done when: 任何实现者都能直接开始补测试
- Verification: 阅读本文件无需再反推需求
- Notes: 采用 plan_ready 等价新状态

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: List the concrete inputs, approvals, tools, context, or prior outputs needed before execution of this phase
- Goal: Expose blockers before the active phase starts
- Inputs / Dependencies: worktree、现有 node_modules/.venv、ace-tool 检索结果
- Procedure / Implementation notes: 识别会受 status 变更影响的 model/schema/service/tests
- Output / Artifact: 依赖列表
- Done when: 后续每个测试文件都有明确落点
- Verification: backend/frontend 关键文件均已定位
- Notes: worker 与 Alembic 也需一并关注

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: Identify the specific materials, components, sources, files, stakeholders, systems, or references that directly affect current-phase execution
- Goal: Ground the work in concrete phase-relevant context
- Inputs / Dependencies: ace-tool 检索、现有测试文件
- Procedure / Implementation notes: 精读 status enum、accepted schema、service transitions、ResearchPage tests、MarkdownContent
- Output / Artifact: 细粒度上下文图
- Done when: 测试修改点与潜在实现点一一对应
- Verification: 无需再做 broad discovery pass
- Notes: 现有 resume/interrupt 测试耦合只在 page/service 层

### 2.2 Break the current phase into executable units
- [x] Task: Split the approved current-phase plan into concrete steps that can be performed, checked, and updated individually
- Goal: Create a reliable execution blueprint for the active phase
- Inputs / Dependencies: 当前 phase 目标与上下文图
- Procedure / Implementation notes:
  - 先补 backend service/schema/worker 红灯
  - 再补 frontend service/type/page/markdown 红灯
  - 最后运行相关测试确认失败原因正确
- Output / Artifact: 可执行步骤分解
- Done when: 每个测试切片都有明确目标
- Verification: 不存在“实现时再想测什么”
- Notes: 每个测试只锁一个行为簇

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: 新增/更新后端测试，锁定 plan_ready + replan/start/stop 行为
- Goal: Convert current-phase planning into real progress with traceable outputs
- Inputs / Dependencies: `backend/tests/services/*`、`backend/src/app/{models,schemas,services,worker}`
- Procedure / Implementation notes:
  - 为 schema accepted 状态约束补测试
  - 为 service 状态迁移和事件补测试
  - 为 worker 非 queued/resuming 的保护逻辑补测试
- Output / Artifact: 后端测试与实现
- Done when: 后端新状态/接口/迁移与测试全部落地
- Verification: `uv run pytest tests\services\test_research_planner.py tests\services\test_research_session_flow.py` + `uv run ruff check src tests\services\test_research_planner.py tests\services\test_research_session_flow.py`
- Notes: 已新增 `plan_ready`、`/plan`、`/start`、`/stop` 与 Alembic migration

### 3.2 Complete remaining executable slices of this phase
- [x] Task: 新增/更新前端测试，锁定 plan review、single-canvas final answer、Mermaid 渲染与旧 UI hard cut
- Goal: Complete the phase without losing traceability
- Inputs / Dependencies: `frontend/src/{services,types,views,components}/*.test*`
- Procedure / Implementation notes:
  - `research.test.ts` 增加 replan/start/stop 合同
  - `researchEvents` 补 plan_ready/started 语义
  - `ResearchPage.test.tsx` 补计划待确认态与旧 resume UI 不出现
  - `MarkdownContent`/相关测试补 Mermaid fenced block
- Output / Artifact: 前端测试与实现
- Done when: 前端 contract、页面与渲染行为完成并通过验证
- Verification: `npm exec vitest run src\services\research.test.ts src\services\researchWorkbench.test.ts src\components\research\ResearchCanvas.test.tsx src\components\research\ResearchPlanningThread.test.tsx src\components\chat\MarkdownContent.test.tsx src\views\ResearchPage.test.tsx` + `npm run typecheck` + `npm run build`
- Notes: 已 hard cut 旧 interrupt/resume 主流程 UI，并引入 `mermaid@11.0.0`

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: Run or document the checks needed to confirm that completed work actually satisfies the intended result of the active phase
- Goal: Prevent premature completion marking
- Inputs / Dependencies: 新增测试
- Procedure / Implementation notes: 分别运行 backend pytest 与 frontend vitest 目标集
- Output / Artifact: 验证记录
- Done when: 所有目标验证通过且输出与结论一致
- Verification: 已完成后端 pytest/ruff 与前端 vitest/typecheck/build
- Notes: 验证为 fresh run

### 4.2 Reconcile phase completion and prepare the next step
- [x] Task: Update fine-grained status, reconcile the medium-granularity plan, document the phase handoff, record archive references, and determine whether to refresh for the next phase or finish the project
- Goal: Leave a complete and honest execution trail for the active phase
- Inputs / Dependencies: 验证记录
- Procedure / Implementation notes: 当前计划已完成，状态与验证同步收口
- Output / Artifact: 同步后的 todo 状态
- Done when: medium/fine/status 三份文件一致并可直接收口
- Verification: medium/fine/status 三份文件一致
- Notes: 当前计划已完成，无 archive
