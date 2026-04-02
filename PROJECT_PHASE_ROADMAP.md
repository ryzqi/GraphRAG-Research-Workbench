# Project Phase Roadmap

## Project Context
- Project Name: Deep Research 右侧主画布破坏性重构
- Project Mode: Multi-phase
- Execution State File / Reference: `PROJECT_EXECUTION_STATE.md`
- Primary User / Stakeholder: 深度研究页面最终用户与仓库维护者
- Customer Problem / Desired Outcome: 研究页需要改为“澄清 -> 计划确认 -> 显式开始 -> 执行 -> 最终回答”单画布流程，避免自动执行和过程/结果分裂布局
- Why Now / Decision Driver: 当前页面已存在 clarify/scoper/runtime 基础，但交互合同与最终渲染不满足新要求
- Overall Goal: 以前后端单一路径完成 Deep Research 显式计划确认流和单画布结果页 hard cut
- Current Active Phase: 已完成，等待用户下一步指令
- Overall Success Criteria:
  - 创建/澄清后先进入计划待确认态，不自动执行
  - 前端提供更新计划与开始执行
  - 右侧主区域统一为单画布状态机
  - 最终回答支持 Markdown 表格与 Mermaid
  - 旧 interrupt/resume 主流程 UI 被 hard cut
- Non-goals:
  - 不做普通聊天/KB Chat 改版
  - 不新增 MCP 执行能力
  - 不保留旧自动执行兼容层
- Artifact Policy / Active Planning Files: `PROJECT_PHASE_ROADMAP.md` + `TASK_TODO_MEDIUM.md` + `TASK_TODO_FINE.md` + `PROJECT_EXECUTION_STATE.md`
- Key Constraints:
  - 最小改动但必须 hard cut 旧交互语义
  - 保持 `/api/v1/research/sessions*` 为公开前缀
  - 保持现有 DeepAgents runtime/subagent 主实现
- Key Risks / Unknowns:
  - status enum 变更涉及 Alembic 与前后端合同
  - 当前前端测试对旧 interrupt/resume 路径耦合较深
- Parked / Deferred Threads:
  - 更细粒度的 subagent 步骤流可视化
  - 过程侧栏的进一步视觉打磨
- Last Updated: 2026-04-02

## Module Map
- Frontend Research Surface
  - Responsibility: 单画布状态机、计划确认交互、最终 Markdown 呈现
  - Key dependencies: `frontend/src/views/ResearchPage.tsx`, `frontend/src/services/research.ts`, `frontend/src/types/researchEvents.ts`
  - Notes: 需要 hard cut 旧 planning/execution 分裂布局
- Backend Research Session Contract
  - Responsibility: create/clarification/replan/start/stop 接口与状态迁移
  - Key dependencies: `backend/src/app/api/v1/endpoints/research.py`, `backend/src/app/services/research_service.py`, `backend/src/app/schemas/research.py`
  - Notes: 需要显式开始执行语义
- Runtime / Rendering
  - Responsibility: 复用 DeepAgents subagent runtime、完善最终 Markdown/Mermaid 渲染
  - Key dependencies: `backend/src/app/services/deep_research_runtime.py`, `frontend/src/components/chat/MarkdownContent.tsx`
  - Notes: 以保留 runtime 为主，重点改前后端合同与展示

## Phase Roadmap
### Phase 1: 合同与测试先行
- Status: Completed
- Objective: 定义 plan-ready 显式开始流，并先补红灯测试
- Scope Boundary: 仅覆盖状态、接口、测试与执行工件，不做大规模 UI 实现
- Modules Involved: Backend Research Session Contract, Frontend Research Surface
- Main Deliverables: 新状态与接口测试、前端 contract/view 测试、执行工件
- Entry Conditions: 已完成方案评审并获准实施
- Completion Conditions: 失败测试稳定复现新需求缺口
- Transition Notes: 进入 Phase 2 实现后端与前端主逻辑

### Phase 2: 后端合同与前端主流程实现
- Status: Completed
- Objective: 实现显式开始/replan/stop 合同与单画布状态机
- Scope Boundary: 覆盖前后端主逻辑与旧 interrupt/resume UI hard cut
- Modules Involved: Frontend Research Surface, Backend Research Session Contract
- Main Deliverables: 新 endpoints、状态迁移、ResearchPage/ResearchCanvas 重构
- Entry Conditions: Phase 1 红灯测试已就位
- Completion Conditions: 目标测试转绿，主流程联调通过
- Transition Notes: 进入 Phase 3 做 Mermaid 与文档/验证收口

### Phase 3: 渲染与收口验证
- Status: Completed
- Objective: Mermaid 渲染、文档与验证闭环
- Scope Boundary: 聚焦 Markdown/Mermaid、合同文档、最终验证
- Modules Involved: Runtime / Rendering, Backend Research Session Contract
- Main Deliverables: Mermaid 支持、API contract 更新、验证记录
- Entry Conditions: 主流程功能已转绿
- Completion Conditions: 目标测试/构建/类型检查通过
- Transition Notes: 若验证通过则项目完成；否则回 Phase 2 修正

## Phase History / Change Log
- 2026-04-02:
  - What changed: 创建执行路线图并确定先测试后实现
  - Why it changed: 该任务是跨前后端破坏性重构，需要 durable roadmap
  - Impact on current or future phases: 后续所有实施与状态汇报以本路线图为准
- 2026-04-02:
  - What changed: 完成显式开始流、单画布页面重构、Mermaid 支持与目标验证
  - Why it changed: 用户要求按批准方案直接实施
  - Impact on current or future phases: 当前计划已交付，后续若继续只需做增量优化

## Archive References
- Phase archive path(s): `archive/`（如后续跨 phase 刷新 todo 再创建）
- Notes about where historical phase todos, state snapshots, or verification artifacts were stored: 当前为首轮执行，暂无归档
