# 后端全量架构审查与纯重构任务计划

## 目标

在不改变当前功能、HTTP 契约、数据契约与运行语义的前提下，完成 `backend` 全量代码审查，并按里程碑对违反 `fastapi-service-architecture` 与仓库 `AGENTS.md` 原则的后端结构做纯架构重构、冗余/遗留代码清理与超大文件拆分。

## 唯一事实源

- 运行时与启动事实源：
  - `F:\毕设\code\backend\src\app\main.py`
  - `F:\毕设\code\backend\src\app\api\v1\endpoints\health.py`
  - `F:\毕设\code\scripts\start_all.ps1`
  - `F:\毕设\code\backend\pyproject.toml`
- 代码结构事实源：
  - `F:\毕设\code\backend\src\app\**\*.py`
  - `F:\毕设\code\backend\tests\*.py`
- 评审准则事实源：
  - `C:\Users\任彦舟\.codex\skills\fastapi-service-architecture\references\*.md`
  - 当前线程 `AGENTS.md`

## 范围

- `backend/src/app`
- `backend/tests`
- 为启动验证所必需时，允许最小修改 `scripts/start_all.ps1`
- 为类型/测试基线所必需时，允许最小修改 `backend/pyproject.toml`
- 允许更新 `docs/superpowers/specs/2026-04-11-backend-architecture-refactor-design.md`
- 允许更新 `docs/superpowers/plans/2026-04-11-backend-architecture-refactor.md`

## 不做项

- 不升级 FastAPI / Pydantic / SQLAlchemy 版本
- 不改 API 路由、请求/响应结构、业务规则与数据库 schema
- 不改前端、infra、部署拓扑
- 不为旧逻辑新增兼容层；仅在现有兼容分支已被真实调用时评估保留

## 约束

- 每个里程碑都执行先红后绿
- 每个里程碑都启动一次后端并检查日志/`/api/v1/ready`
- 每个里程碑启动通过后创建一次 git commit
- 未完成 fresh verification 前，状态只能是“已定位”或“已修改未验证”

## 验收标准

1. `backend/src/app` 全部 Python 文件已纳入审查记录，不遗漏目录。
2. 对确认存在的结构问题完成纯重构，不引入功能变化。
3. 所有大于 800 行且职责混杂的文件都被评估；对可安全拆分者完成拆分。
4. 每个里程碑都有对应的红绿测试、启动验证与提交证据。
5. `findings.md` 明确记录：
   - 是否符合 FastAPI 架构原则
   - 是否有冗余代码
   - 是否符合 AGENTS 原则
   - 是否存在超大文件
   - 是否存在遗留代码

## 当前判定

- 当前任务属于 `L3`：后端目录大、耦合深、超大文件多，必须拆成多轮 spec/plan/execute/verify/commit 闭环。
- 已完成设计审批，执行路径采用方案 C：按高耦合业务链分里程碑推进。
- 第一轮不引入 `domain/` 或 `use_cases/` 新层级；先按最小形态收敛启动装配和 API 边界。

## 里程碑

### M0：基线审查与计划冻结
- [x] 建立 planning 文档
- [x] 建立 spec / implementation plan 文档
- [x] 盘点目录、行数、超大文件、遗留标记
- [x] 定义后续里程碑边界与验证命令
- [x] 完成设计审批并冻结 M1 变更边界

### M1：启动与 API 边界重构
- [x] 审查并重构 `app.main` 启动装配边界
- [x] 抽离生命周期/应用装配辅助模块，保持入口语义不变
- [x] 审查并收敛 `api/v1/endpoints/chats.py` 的依赖构造与流式辅助逻辑
- [x] 红绿验证后启动后端并提交

### M2：Deep Research 服务链重构
- [x] 审查并拆分 `services/deep_research_runtime.py`
- [x] 审查并拆分 `services/research_service.py`
- [x] 复核相关 research 支撑文件的职责边界
- [x] 红绿验证后启动后端并提交

### M3：KB Chat / Retrieval 服务链重构
- [x] 审查并拆分 `services/kb_chat_service.py`
- [x] 审查并拆分 `services/query_rewrite_service.py`
- [x] 审查并拆分 `services/retrieval_service.py`
- [x] 红绿验证后启动后端并提交

### M4：General Chat / Ingestion / Worker 重构
- [x] 审查并拆分 `services/general_chat_service.py`
- [x] 审查并拆分 `services/ingestion_batch_service.py`
- [x] 审查并拆分 `services/parsing/material_parser.py`
- [x] 复核 `worker/tasks/*` 边界
- [x] 红绿验证后启动后端并提交

### M5：Agents / Integrations / Settings 收尾
- [x] 审查并拆分 `agents/tools/web_search.py`
- [x] 审查并拆分 `agents/kb_chat_agentic_graph.py`
- [x] 审查并拆分 `agents/kb_chat_trace_display_contract.py`
- [x] 审查 `core/settings.py` 与剩余 >800 行文件
- [x] 红绿验证后启动后端并提交

### M6：全量复核与交付
- [x] 复核剩余未触及文件是否满足边界要求
- [x] 执行综合验证
- [x] 准备最终结论与遗留风险说明

## 错误记录

| 阶段 | 错误 | 处理 |
| --- | --- | --- |
| M0 | `git status --short` 受到 pytest 临时目录权限警告干扰 | 改用 `--untracked-files=no` 并忽略临时缓存目录 |
| M0 | `apply_patch` 在当前 Windows 会话报辅助进程/防火墙规则错误 | 改用工作区内 PowerShell 等价编辑，保留最小 diff 与日志 |
| M1 | 直接启动后端时报 `ConnectionRefusedError ('127.0.0.1', 5433)` | 先启动本地 infra，再重跑后端启动验证 |
| M1 | `infra/up.ps1` 在当前 PowerShell 解释器下出现 UTF-8 误解码导致 parser error | 改用 PowerShell 7 执行 `infra/up.ps1` |
