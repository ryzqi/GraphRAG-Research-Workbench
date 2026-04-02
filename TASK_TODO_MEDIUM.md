# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference: None
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Project Modules: Frontend Research Surface / Backend Research Session Contract / Runtime Rendering
- Brownfield Context / Codebase Map: `backend/src/app/{models,schemas,services,api/v1/endpoints}/research*`, `backend/src/app/worker/tasks/research.py`, `frontend/src/{views,types,hooks/services/components}/research*`, `frontend/src/components/chat/MarkdownContent.tsx`
- Primary User / Stakeholder: 深度研究页面用户
- Customer Problem / Desired Outcome: 研究页面需要从自动执行改为计划确认后执行，并统一单画布展示结果
- Why Now / Decision Driver: 现有 clarify/runtime 已具备基础，但交互合同与结果渲染不符合目标
- Phase Roadmap Summary: Phase 1 先落测试与合同；Phase 2 实现主流程；Phase 3 做 Mermaid 与收口验证
- Current Phase: Phase 1 - 合同与测试先行
- Phase Goal: 用红灯测试锁定新显式开始流、stop hard cut、Mermaid 渲染能力
- Phase Scope: 新状态/接口/页面预期测试；不在本阶段完成实际实现
- Non-goals: 不在本阶段重写所有 UI 细节；不做普通聊天路径修改
- Phase Deliverables: 后端 contract/service 测试、前端 service/type/view/rendering 测试、执行工件
- Active Execution Wave: 已完成
- Entry Criteria: 已获用户批准实施
- Exit Criteria / Done Definition: 新需求缺口可通过失败测试直接观察到
- Transition Notes / Next Phase Trigger: 红灯测试稳定后进入 Phase 2 实现
- Previous Phase Summary: None

## Part 1: Current phase requirement and scope
### 1.1 Clarify the current phase objective
- [x] Task: Rewrite the approved current-phase request into a concrete implementation objective
- Goal: Make the current execution target explicit and testable
- Done when: 当前 phase 的新增状态/接口/渲染目标被写清楚
- Deliverables: Phase 1 目标说明
- Notes: 以显式开始流和 Mermaid 支持为核心

### 1.2 Confirm current phase constraints and dependencies
- [x] Task: Summarize the main constraints, dependencies, and external conditions for this phase
- Goal: Prevent execution drift and hidden blockers in the current phase
- Done when: 状态枚举、Alembic、ResearchPage 测试耦合点已识别
- Deliverables: 依赖与风险摘要
- Notes: 保持 DeepAgents runtime，不扩改 MCP

## Part 2: Current phase research and planning
### 2.1 Review relevant context for this phase
- [x] Task: Identify and summarize the most relevant existing context for the active phase
- Goal: Reuse known information before creating new structure
- Done when: 关键文件与测试入口已盘点
- Deliverables: 关键上下文摘要
- Notes: 已定位 backend schemas/service/model/worker 与 frontend view/types/hooks/tests

### 2.2 Establish the execution plan for this phase
- [x] Task: Define the main workstreams and execution sequence for the active phase
- Goal: Create a stable, reviewable plan for the current phase
- Done when: 当前 phase 的执行顺序明确
- Deliverables: 当前 phase 执行计划
- Notes: 先后端红灯，再前端红灯

## Part 3: Current phase execution
### 3.1 Complete the first major workstream of this phase
- [x] Task: Finish backend red tests for explicit plan confirmation flow and stop hard cut
- Goal: Lock the new session contract before code changes
- Done when: 后端测试覆盖 create/clarification/replan/start/stop 新语义
- Deliverables: 后端测试与实现
- Notes: 已覆盖 model/schema/service 与 migration

### 3.2 Complete remaining major workstreams of this phase
- [x] Task: Finish frontend red tests for single-canvas flow and mermaid rendering
- Goal: Lock UI and rendering expectations before implementation
- Done when: 前端服务、类型、页面、Markdown 渲染测试失败复现
- Deliverables: 前端测试与实现
- Notes: 已 hard cut 旧 interrupt/resume 主流程 UI

## Part 4: Verification and transition
### 4.1 Verify current-phase outcomes
- [x] Task: Confirm that the completed work satisfies the approved current-phase plan
- Goal: Ensure the phase is actually ready to report as complete
- Done when: 目标实现已完成并由 fresh verification 支撑
- Deliverables: 验证记录
- Notes: 已完成 backend pytest/ruff 与 frontend vitest/typecheck/build

### 4.2 Reconcile status and decide transition
- [x] Task: Summarize outcomes, update completion status honestly, record archive references, and determine whether to close or move into the next phase
- Goal: Leave a clear high-level audit trail and a clean handoff decision
- Done when: 当前任务结果、验证与下一步都可直接汇报
- Deliverables: 状态摘要与收口说明
- Notes: 当前计划已收口，无需 archive
