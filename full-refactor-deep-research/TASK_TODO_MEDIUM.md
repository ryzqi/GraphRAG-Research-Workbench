# Task Todo - Medium

## Project / Phase Context
- Roadmap File / Reference: `full-refactor-deep-research/PROJECT_PHASE_ROADMAP.md`
- Execution State File / Reference: `full-refactor-deep-research/PROJECT_EXECUTION_STATE.md`
- Previous Phase Archive Reference: 无
- Project Mode: Multi-phase
- Artifact Policy / Active Planning Files:
  - `PROJECT_PHASE_ROADMAP.md`
  - `TASK_TODO_MEDIUM.md`
  - `TASK_TODO_FINE.md`
  - `PROJECT_EXECUTION_STATE.md`
- Project Modules: 后端研究域模型与持久化；契约与会话编排
- Brownfield Context / Codebase Map:
  - 当前 research ORM / schema / service / endpoint 文件已被删除，仅残留 pycache 与 `a6b8c9d0e1f2_remove_research_stack.py`
  - 前端仍保留 `/api/v1/research/runs*` 旧调用
  - `full-refactor-deep-research/*.md` 已给出 proposal/design/spec/tasks
  - 最新官方 Deep Agents 用法已在 2026-03-29 重新核对：`create_deep_agent` 核心配置、`stream(... version=\"v2\", subgraphs=True)`、`interrupt_on` 需配 checkpointer、PyPI stable 为 `0.4.12`，存在更新的 `0.5.0a2` 预发布
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 从“研究后端被移除”恢复到“当前研究单路径可连续建设”的可执行基础
- Why Now / Decision Driver: runtime / API / frontend 后续工作都依赖稳定三表和契约底座
- Phase Roadmap Summary: 先做模型/契约/planner 基础，再接 runtime、再接当前 API/前端、最后做门禁
- Current Phase: Phase 1 - 研究域模型与契约底座
- Phase Goal: 完成 Task 1-3 的基础壳层，当前正在推进 Task 2（研究 schema 契约）
- Phase Scope:
  - 包含：三表 ORM、状态机约束、Alembic 迁移、Task 1 测试
  - 不包含：Deep Agents 依赖接入、运行时、API、前端、demo 启动
- Non-goals:
  - 不恢复旧 run-centric research backend
  - 不在本轮实现 planner / runtime 业务逻辑
- Phase Deliverables:
  - `backend/src/app/models/research_session.py`
  - `backend/src/app/models/research_event.py`
  - `backend/src/app/models/research_artifact.py`
  - `backend/src/app/db/base.py` 注册
  - Alembic 新迁移
  - `backend/tests/research/test_models_runtime_schema.py`
- Active Execution Wave: Task 2 提交收尾（同步状态 + git commit）
- Entry Criteria:
  - 最新官方 Deep Agents 文档已核对
  - 当前 Alembic head = `a6b8c9d0e1f2`
- Exit Criteria / Done Definition:
  - 三表模型与迁移落地
  - Task 1 对应测试先红后绿完成
  - `uv run pytest backend/tests/research/test_models_runtime_schema.py -q` 通过
  - 本任务完成后 git 提交
- Transition Notes / Next Phase Trigger: Task 1 提交后继续在 Phase 1 内推进 Task 2
- Previous Phase Summary: 无

## Part 1: 当前阶段需求与范围
### 1.1 锁定 Task 1 目标
- [x] Task: 将 `tasks.md` Task 1 重写为可执行目标
- Goal: 明确本轮只恢复模型/迁移/测试，不扩散到 runtime
- Done when: Task 1 边界与验收清晰
- Deliverables: 当前执行目标说明
- Notes: 以 `research_sessions / research_events / research_artifacts` 为唯一事实源

### 1.2 确认 Task 1 约束与依赖
- [x] Task: 汇总本轮依赖与风险
- Goal: 避免写出又要被后续 hard cut 的兼容层
- Done when: 约束、依赖、风险已记录
- Deliverables: 当前约束摘要
- Notes: 禁止恢复旧 `AgentRunType.RESEARCH`

## Part 2: 当前阶段研究与计划
### 2.1 复核 Task 1 上下文
- [x] Task: 审查现有设计文档、迁移基线、旧 research 移除迁移与最新官方 Deep Agents 文档
- Goal: 让模型设计与当前 baseline、一手文档一致
- Done when: 当前 task 的事实源已确认
- Deliverables: 上下文摘要
- Notes: 官方文档只作为 runtime 设计约束，不直接决定本轮 ORM 字段全部细节

### 2.2 确立 Task 1 执行顺序
- [x] Task: 采用“planning artifacts -> failing test -> models/migration -> verify -> commit”顺序
- Goal: 满足 requirement-to-delivery + TDD + git 提交流程
- Done when: 执行顺序稳定
- Deliverables: Task 1 执行顺序
- Notes: 完成后继续推进 Task 2

## Part 3: 当前阶段执行
### 3.1 完成 Task 1 模型与迁移
- [x] Task: 落地 research 三表模型、状态机 helper、base 注册与 Alembic 迁移
- Goal: 恢复研究域持久化骨架
- Done when: ORM 与迁移文件完成，且无旧 research 兼容路径残留
- Deliverables: 模型与迁移文件
- Notes: 已新增 `research_session.py` / `research_event.py` / `research_artifact.py`，并生成迁移 `38f4aa0f8d91_reintroduce_research_session_tables.py`

### 3.2 完成 Task 1 回归测试
- [x] Task: 新增并通过 Task 1 对应测试
- Goal: 证明唯一约束、终态不可逆、thread_id/namespace 约束真实存在
- Done when: 先红后绿记录完整
- Deliverables: 测试文件与验证输出
- Notes: RED=`ModuleNotFoundError: app.models.research_artifact`；GREEN=`5 passed`

### 3.3 完成 Task 2 研究 schema 契约
- [x] Task: 新建 `backend/src/app/schemas/research.py` 并补齐 Task 2 对应测试
- Goal: 冻结 create session / plan snapshot / event envelope / interrupt-resume / artifacts 契约
- Done when: `backend/tests/research/test_schemas_research.py` 先红后绿完成，且与 Task 1 不冲突
- Deliverables: schema 文件与验证输出
- Notes: RED=`ModuleNotFoundError: No module named 'app.schemas.research'`；GREEN=`5 passed`；联合回归=`10 passed`

## Part 4: 验证与切换
### 4.1 验证 Task 1 产物
- [x] Task: 运行 Task 1 定向 pytest / Alembic 检查
- Goal: 为 git 提交提供新鲜证据
- Done when: 验证输出支持“已验证通过”
- Deliverables: 验证记录
- Notes: `uv run pytest tests/research/test_models_runtime_schema.py -q` -> `5 passed`; `uv run ruff check ...` -> `All checks passed!`; `uv run alembic heads` -> `38f4aa0f8d91 (head)`

### 4.2 同步状态并提交
- [x] Task: 更新 todo / state，完成 Task 1 git 提交，并锁定下一个任务为 Task 2
- Goal: 保持一次一任务的执行纪律
- Done when: 已提交且下个任务明确
- Deliverables: 提交记录与下一任务决策
- Notes: 已提交 `0c5fa63 feat(research): restore research persistence foundation`；下一任务锁定为 `backend/src/app/schemas/research.py` 与 `backend/tests/research/test_schemas_research.py`

### 4.3 提交 Task 2 并切换到 Task 3
- [ ] Task: 完成 Task 2 git 提交，并将当前活动任务切到 preflight planner（Task 3）
- Goal: 继续保持“一次一任务、任务完成即提交”
- Done when: 已提交 Task 2，execution state 指向 Task 3
- Deliverables: 提交记录与下一任务决策
- Notes: 提交前不宣称 Task 2 完成
