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
- Project Modules: Deep Agents runtime 与 source-aware tooling；契约与会话编排
- Brownfield Context / Codebase Map:
  - `backend/pyproject.toml`
  - `backend/src/app/agents/tool_calling/registry.py`
  - `backend/src/app/services/research_planner.py`
  - `backend/src/app/schemas/research.py`
  - `full-refactor-deep-research/design.md`
  - 官方 Deep Agents 文档：overview / customization / backends / streaming / release policy / PyPI `deepagents`
- Primary User / Stakeholder: 当前仓库维护者 / 毕设演示链路
- Customer Problem / Desired Outcome: 让 Phase 1 的业务壳层真正接上唯一的 Deep Agents runtime，而不是继续停留在规划层
- Why Now / Decision Driver: 没有 runtime 单入口，Task 5-10 都无法建立在真实执行引擎之上
- Phase Roadmap Summary: 先完成 Task 4 runtime 单入口，再推进 Task 5 source-aware routing，最后做 Task 6 service/persistence orchestration
- Current Phase: Phase 2 - Deep Agents 单引擎运行时与来源路由
- Current Phase Inputs:
  - Phase 1 提交：`0c5fa63`、`efc6693`、`c3ccdf2`
  - 当前 backend 已锁定 `deepagents==0.4.12`
  - 官方约束：`create_deep_agent` 顶层配置、`subgraphs=True` + `version="v2"` 流式、`interrupt_on` 需配 `checkpointer`
- Active Execution Wave: Task 4 已完成；下一任务 = Task 5 source-aware routing
- Phase Goal: 完成 Task 4（Deep Agents 单引擎运行时）
- Phase Scope:
  - 包含：依赖策略、runtime types、runtime skeleton、研究模式工具装配约束、Task 4 测试
  - 不包含：Task 5 source-aware routing、Task 6 service、Task 7+ API/前端
- Non-goals:
  - 不保留旧 run-centric runtime
  - 不在此轮接通完整外部 provider 调用
- Phase Deliverables:
  - `backend/src/app/services/deep_research_runtime.py`
  - `backend/src/app/services/research_runtime_types.py`
  - `backend/tests/research/test_deep_research_runtime.py`
  - `backend/pyproject.toml` / `uv.lock`（若需）
- Entry Criteria:
  - Phase 1 已完成并归档
  - 最新 Deep Agents 官方文档已核对
- Phase Exit Criteria:
  - Task 4 定向测试通过
  - runtime 单入口与依赖策略落地
  - 已完成 git 提交
- Next Phase Trigger / Transition Notes: 提交后把 active execution wave 切换到 Task 5
- Previous Phase Summary: Phase 1 已完成模型、schema、planner 基础壳层，并形成 13 条 research 定向测试通过的 stop point

## Part 1: 当前阶段需求与范围
### 1.1 固化 Task 4 可执行目标
- [x] Task: 只实现 `tasks.md` Task 4 所需 runtime types、single-entry runtime skeleton、依赖与测试
- Goal: 让本轮改动聚焦在 Deep Agents runtime 自身
- Inputs / Dependencies: `tasks.md`, design, official Deep Agents docs, current backend deps
- Procedure / Implementation notes: 先把 runtime 架子立住，再在下一任务接入 source-aware provider
- Output / Artifact: Task 4 目标声明
- Done when: 不需要重新解释“本轮做什么”
- Verification: medium todo 与 roadmap 描述一致
- Notes: 不在本轮实现 ResearchService / API

### 1.2 列出 Task 4 依赖与先决条件
- [x] Task: 确认 `deepagents` 版本策略、langchain/langgraph 兼容面、测试目录与 runtime 入口文件位置
- Goal: 避免依赖安装后再返工 runtime 设计
- Inputs / Dependencies: `pyproject.toml`, `uv.lock`, official docs / PyPI, current codebase
- Procedure / Implementation notes: 若 stable 缺关键 API，再升级到 pre-release；要把判断依据写入 state
- Output / Artifact: 依赖清单
- Done when: 后续每个动作都有明确依赖依据
- Verification: 能直接列出待改文件与版本策略
- Notes: 已选 stable `deepagents==0.4.12`；本地签名核对已满足 Task 4 所需 API，无需切到 pre-release

## Part 2: 当前阶段研究与拆解
### 2.1 详细检查 Task 4 相关上下文
- [x] Task: 读取 `pyproject.toml`、tool registry、Phase 1 输出、官方 Deep Agents customization/backends/streaming 文档
- Goal: 让 runtime 设计既匹配本仓结构又不偏离当前官方用法
- Inputs / Dependencies: 本地代码与官方文档
- Procedure / Implementation notes: 重点确认 `create_deep_agent` 顶层参数、后端分层与 streaming 合同
- Output / Artifact: 当前上下文图
- Done when: 已确认 runtime 不应再走旧 research service / run-centric 兼容路径
- Verification: 规划文档与实现方向一致
- Notes: Phase 2 的事实源仍以官方文档与本仓代码为准

### 2.2 把 Task 4 拆为可执行单元
- [x] Task: 拆成“锁定版本策略 -> 写 failing test -> 接入依赖/代码 -> 跑绿 -> 更新 todo/state -> 提交”
- Goal: 保持一步一验
- Inputs / Dependencies: TDD 规则、Task 4 验收
- Procedure / Implementation notes: 不在测试之前写 production runtime
- Output / Artifact: 执行步骤清单
- Done when: 每个子步骤可独立勾选
- Verification: 无含糊的“大概做完”
- Notes: 当前 active wave 先做 3.1-3.3

## Part 3: 当前阶段执行
### 3.1 新增 Task 4 回归测试（RED）
- [x] Task: 新建 `backend/tests/research/test_deep_research_runtime.py`
- Goal: 先让测试因 runtime 缺失或装配错误而失败
- Inputs / Dependencies: Task 4 验收、官方文档、现有 Phase 1 输出
- Procedure / Implementation notes: 覆盖单入口、禁用 MCP、后端分层、恢复配置、主/子代理模型参数
- Output / Artifact: failing test
- Done when: pytest 对该文件稳定失败且失败原因正确
- Verification: `uv run pytest tests/research/test_deep_research_runtime.py -q`
- Notes: 红测已确认：`uv run pytest tests/research/test_deep_research_runtime.py -q` 因缺少 `app.services.deep_research_runtime` 在收集阶段失败

### 3.2 锁定依赖与 runtime types（GREEN 1）
- [x] Task: 选择并接入 `deepagents` 依赖策略，补齐 `research_runtime_types.py`
- Goal: 为 runtime skeleton 提供稳定的依赖与类型地基
- Inputs / Dependencies: failing test、官方文档、当前依赖图
- Procedure / Implementation notes: 若需修改 `pyproject.toml` / `uv.lock`，必须保留明确版本理由
- Output / Artifact: 依赖变更与 runtime types
- Done when: 测试不再因缺依赖/缺类型失败
- Verification: 重新跑定向 pytest
- Notes: 已锁定 `deepagents==0.4.12`，并落地 provider / backend / stream / spillover 固定策略

### 3.3 落地 runtime skeleton 与装配约束（GREEN 2）
- [x] Task: 实现 `deep_research_runtime.py`
- Goal: 恢复研究模式唯一 runtime 入口
- Inputs / Dependencies: Task 4 验收、依赖安装、runtime types、tool registry 现状
- Procedure / Implementation notes:
  - `create_deep_agent` 为唯一入口
  - 研究模式工具装配显式排除 MCP
  - `checkpointer` / `thread_id` / `interrupt_on` / backend routing 显式可测
- Output / Artifact: runtime 文件
- Done when: 测试转绿
- Verification: `uv run pytest tests/research/test_deep_research_runtime.py -q`
- Notes: 本轮未发现需删除的旧 runtime 文件；当前 research runtime 仅保留 `deep_research_runtime.py`

### 3.4 运行定向验证并修复（GREEN 3）
- [x] Task: 跑 pytest / ruff / 必要的依赖验证，失败则修复
- Goal: 获得 fresh verification
- Inputs / Dependencies: 测试文件、依赖、runtime 代码
- Procedure / Implementation notes: 至少包含 red -> green 证据与最终通过输出
- Output / Artifact: 验证记录
- Done when: 定向 pytest / ruff 通过
- Verification:
  - `uv run pytest tests/research/test_deep_research_runtime.py -q`
  - `uv run ruff check ...`
- Notes:
  - `uv run pytest tests/research/test_deep_research_runtime.py -q` -> `5 passed`
  - `uv run pytest tests/research/test_models_runtime_schema.py tests/research/test_schemas_research.py tests/research/test_research_planner.py tests/research/test_deep_research_runtime.py -q` -> `18 passed`
  - `uv run ruff check src/app/services/deep_research_runtime.py src/app/services/research_runtime_types.py tests/research/test_deep_research_runtime.py` -> `All checks passed!`

## Part 4: 验证与切换
### 4.1 验证本阶段已完成输出
- [x] Task: 复核 Task 4 验收与 medium todo 同步
- Goal: 防止“代码过了但 todo 仍旧过时”
- Inputs / Dependencies: 定向验证输出、planning files
- Procedure / Implementation notes: 只在证据和文档一致后勾选
- Output / Artifact: 当前阶段验证记录
- Done when: medium / fine / state / git 提交描述一致
- Verification: 手动交叉检查 planning files + git diff
- Notes: 当前仅覆盖 Task 4 切换

### 4.2 准备下一个任务
- [x] Task: 更新 planning/state，并提交 Task 4
- Goal: 让下一轮从 Task 5 直接起步
- Inputs / Dependencies: Task 4 已验证通过
- Procedure / Implementation notes: 提交后下一任务默认是 source-aware routing（Task 5）
- Output / Artifact: 下一任务就绪状态
- Done when: 下一任务与阻塞点明确
- Verification: `git status --short`
- Notes: 下一任务为 Task 5（source-aware routing / provider 工具族）
