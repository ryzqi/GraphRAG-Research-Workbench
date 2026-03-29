# Task Todo - Fine

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
  - `backend/alembic/versions/a6b8c9d0e1f2_remove_research_stack.py`
  - `backend/src/app/db/base.py`
  - `backend/src/app/models/agent_run.py`
  - `full-refactor-deep-research/tasks.md`
  - `full-refactor-deep-research/specs/research-persistence-model/spec.md`
  - 官方 Deep Agents 文档：customization / streaming / release policy + PyPI `deepagents`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 为后续研究 runtime 重建一个可迁移、可测试、可扩展的后端事实源
- Why Now / Decision Driver: 没有三表与状态机，后续 planner/runtime/API 全部无从落地
- Phase Roadmap Summary: 先完成 Task 1，再继续 Task 2/3，然后进入 runtime 阶段
- Current Phase: Phase 1 - 研究域模型与契约底座
- Current Phase Inputs:
  - `tasks.md` Task 1
  - `specs/research-persistence-model/spec.md`
  - 当前 Alembic head = `a6b8c9d0e1f2`
  - 当前 backend 中无 research ORM / schema / service 文件
- Active Execution Wave: 3.5 同步状态并 git 提交
- Phase Goal: 完成 Task 1（模型 / 迁移 / 测试 / 提交）
- Phase Scope:
  - 包含：模型、迁移、定向测试、todo/state 更新、git 提交
  - 不包含：Task 2 schema、Task 3 planner、runtime 接入
- Non-goals:
  - 不新增旧 `/runs` 接口兼容逻辑
  - 不修改前端研究调用
- Phase Deliverables:
  - `backend/src/app/models/research_session.py`
  - `backend/src/app/models/research_event.py`
  - `backend/src/app/models/research_artifact.py`
  - `backend/alembic/versions/*_reintroduce_research_session_tables.py`
  - `backend/tests/research/test_models_runtime_schema.py`
- Entry Criteria:
  - Deep Agents 官方当前约束已核对：`create_deep_agent` 顶层配置、`stream(... version=\"v2\", subgraphs=True)`、`interrupt_on + checkpointer`
  - 当前仓库 research 后端为空白基线
- Phase Exit Criteria:
  - Task 1 定向测试通过
  - todo/state 与 git 状态已同步
  - 已完成 git 提交
- Next Phase Trigger / Transition Notes: 提交后把 active execution wave 切换到 Task 2.1-2.6
- Previous Phase Summary: 无

## Part 1: 当前阶段需求与范围
### 1.1 固化 Task 1 可执行目标
- [x] Task: 只实现 `tasks.md` Task 1 所需模型、迁移、测试与注册
- Goal: 让本轮改动最小化
- Inputs / Dependencies: `tasks.md`, persistence spec, 当前 baseline
- Procedure / Implementation notes: 模型可为后续 task 预留必要字段，但不得提前接入 runtime/service
- Output / Artifact: Task 1 目标声明
- Done when: 不需要重新解释“本轮做什么”
- Verification: medium todo 与 roadmap 描述一致
- Notes: 后续契约字段在 Task 2 落地

### 1.2 列出 Task 1 依赖与先决条件
- [x] Task: 确认当前 head、现有迁移删除点、测试目录与模型注册入口
- Goal: 避免迁移链断裂
- Inputs / Dependencies: Alembic head/current, `db/base.py`, `models/__init__.py`
- Procedure / Implementation notes: 新迁移必须基于 `a6b8c9d0e1f2`
- Output / Artifact: 依赖清单
- Done when: 后续每个动作都有对应入口
- Verification: 能直接列出待改文件
- Notes: `uv run alembic heads && uv run alembic current` 已确认

## Part 2: 当前阶段研究与拆解
### 2.1 详细检查 Task 1 相关上下文
- [x] Task: 读取移除 research 的迁移、现有 `agent_run` 模型、persistence spec、design/task 文档与最新官方 Deep Agents 用法
- Goal: 让本轮模型边界既匹配设计又不重新引入旧耦合
- Inputs / Dependencies: 本地代码与官方文档
- Procedure / Implementation notes: 将“业务状态机”和“Deep Agents runtime”清晰分层
- Output / Artifact: 当前上下文图
- Done when: 已确认 research 不应重新耦合到 `agent_runs`
- Verification: 规划文档与实现方向一致
- Notes: Deep Agents 文档更多约束 Phase 2，但已决定本轮保留 `thread_id` / `phase` / `namespace` 等 future-proof 字段

### 2.2 把 Task 1 拆为可执行单元
- [x] Task: 拆成“写 failing test -> 跑红 -> 写模型 -> 写迁移 -> 跑绿 -> 更新 todo/state -> 提交”
- Goal: 保持一步一验
- Inputs / Dependencies: TDD 规则、Task 1 验收
- Procedure / Implementation notes: 不在测试之前写 production model
- Output / Artifact: 执行步骤清单
- Done when: 每个子步骤可独立勾选
- Verification: 无含糊的“大概做完”
- Notes: 当前 active wave 先做 3.1-3.3

## Part 3: 当前阶段执行
### 3.1 新增 Task 1 回归测试（RED）
- [x] Task: 新建 `backend/tests/research/test_models_runtime_schema.py`，直接断言研究模型与约束
- Goal: 先让测试因模型缺失或约束缺失而失败
- Inputs / Dependencies: persistence spec、Task 1 验收
- Procedure / Implementation notes: 覆盖三表、唯一约束、终态不可逆、thread_id/namespace 约束
- Output / Artifact: failing test
- Done when: pytest 对该文件稳定失败且失败原因正确
- Verification: `uv run pytest tests/research/test_models_runtime_schema.py -q`
- Notes: RED 结果为 `ModuleNotFoundError: No module named 'app.models.research_artifact'`

### 3.2 落地三表模型与状态机 helper（GREEN 1）
- [x] Task: 添加 `research_session.py`、`research_event.py`、`research_artifact.py`
- Goal: 恢复后端研究事实源骨架
- Inputs / Dependencies: failing test、existing ORM patterns
- Procedure / Implementation notes:
  - `ResearchSession` 保留 `thread_id`、状态机、planner/runtime/finalizer phase 字段
  - `ResearchEvent` 保留 `event_id`、`sequence`、`phase`、`namespace`、`idempotency_key`
  - `ResearchArtifact` 保留 session-scoped artifact key 与 future-proof metadata
- Output / Artifact: 三个 ORM 模型
- Done when: 测试不再因缺模块/缺字段失败
- Verification: 重新跑定向 pytest
- Notes: 保持 session 独立三表，不恢复旧 `research_report` / `AgentRunType.RESEARCH`

### 3.3 注册模型并补齐迁移（GREEN 2）
- [x] Task: 更新 `db/base.py` 并新增 Alembic 迁移
- Goal: 让 schema 与 ORM 对齐
- Inputs / Dependencies: 新模型、当前 head
- Procedure / Implementation notes: 迁移基于 `a6b8c9d0e1f2`
- Output / Artifact: base 注册与新迁移文件
- Done when: Alembic head 可识别新修订
- Verification: `uv run alembic heads`
- Notes: 自动生成迁移后手工删除了误伤的 `store` / `store_migrations` 删除语句，并补回 `research_session_status` downgrade drop

### 3.4 运行定向验证并修复（GREEN 3）
- [x] Task: 跑 pytest 与 Alembic 检查，必要时修复失败
- Goal: 获得 fresh verification
- Inputs / Dependencies: 测试文件、模型、迁移
- Procedure / Implementation notes: 至少包含 red -> green 证据和最终通过输出
- Output / Artifact: 验证记录
- Done when: 定向 pytest 通过，Alembic head 正常
- Verification:
  - `uv run pytest tests/research/test_models_runtime_schema.py -q`
  - `uv run alembic heads`
- Notes: 已额外执行 `uv run ruff check ...`，结果 `All checks passed!`

### 3.5 同步执行工件并 git 提交
- [ ] Task: 更新 roadmap/todo/state 的完成状态，并提交 Task 1
- Goal: 满足“一次只完成一个任务，完成后 git 提交”
- Inputs / Dependencies: 3.4 成功验证
- Procedure / Implementation notes: 提交信息必须准确描述 Task 1
- Output / Artifact: git commit
- Done when: `git status` 干净或仅剩下一任务新改动
- Verification: `git status --short`
- Notes: 提交后才允许切换到 Task 2

## Part 4: 验证与切换
### 4.1 验证本阶段已完成输出
- [x] Task: 复核 Task 1 验收与 medium todo 同步
- Goal: 防止“代码过了但 todo 仍旧过时”
- Inputs / Dependencies: 定向验证输出、planning files
- Procedure / Implementation notes: 只在证据和文档一致后勾选
- Output / Artifact: 当前阶段验证记录
- Done when: medium / fine / state / git 提交描述一致
- Verification: 手动交叉检查 planning files + git diff
- Notes: 当前仅剩 Task 1 git 提交动作未完成

### 4.2 准备下一个任务
- [ ] Task: 将 active execution wave 切到 Task 2，并写入 execution state
- Goal: 让下一轮从 Task 2 直接起步
- Inputs / Dependencies: Task 1 已提交
- Procedure / Implementation notes: 不刷新 phase todo，只更新 active wave
- Output / Artifact: 下一任务就绪状态
- Done when: 下一任务与阻塞点明确
- Verification: `PROJECT_EXECUTION_STATE.md` 已更新
- Notes: 下一任务默认是研究 schema 契约（Task 2）
