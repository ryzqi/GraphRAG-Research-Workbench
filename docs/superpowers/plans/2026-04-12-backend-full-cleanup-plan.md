# Backend 全量安全清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `backend` 全量一方代码范围内，逐文件完成安全清理，移除确认无用的实现，同时保持功能、契约和迁移链路完整。

**Architecture:** 先固定唯一事实源和逐文件清单，再按子域拆分审查。每个子域先做动态入口核查和候选项论证，再做最小化删除或收缩，并用针对性测试或等价验证证明未误伤功能。

**Tech Stack:** Python, FastAPI, Celery, SQLAlchemy, Alembic, LangGraph/LangChain, pytest, pyright

---

### Task 1: 建立基线、分支和逐文件清单

**Files:**
- Create: `F:\毕设\code\task_plan.md`
- Create: `F:\毕设\code\findings.md`
- Create: `F:\毕设\code\progress.md`
- Create: `F:\毕设\code\docs\superpowers\specs\2026-04-12-backend-full-cleanup-design.md`
- Create: `F:\毕设\code\docs\superpowers\plans\2026-04-12-backend-full-cleanup-plan.md`
- Create: `F:\毕设\code\docs\backend-code-cleanup-checklist-2026-04-12.md`

- [ ] Step 1: 用 `git ls-files backend` 固定文件范围，生成逐文件清单
- [ ] Step 2: 创建专用分支，避免直接在 `master` 上做清理
- [ ] Step 3: 记录动态注册点、大文件热点、风险子域
- [ ] Step 4: 提交基线文档里程碑

### Task 2: 子域结构审查与候选项论证

**Files:**
- Modify: `F:\毕设\code\findings.md`
- Modify: `F:\毕设\code\progress.md`
- Modify: `F:\毕设\code\docs\backend-code-cleanup-checklist-2026-04-12.md`

- [ ] Step 1: 为以下子域分别产出候选清理项和高风险说明
  - `api/bootstrap/core/db/integrations/worker`
  - `agents/tools/search/prompts`
  - `services` 非 research
  - `research` 运行时与报告链路
- [ ] Step 2: 对每个候选项确认“静态引用 + 动态入口 + 配置驱动”三类证据
- [ ] Step 3: 把“仅分析无改动”的文件也记入清单完成状态

### Task 3: 入口与基础层清理

**Files:**
- Modify: `backend/src/app/api/**`
- Modify: `backend/src/app/bootstrap/**`
- Modify: `backend/src/app/core/**`
- Modify: `backend/src/app/db/**`
- Modify: `backend/src/app/integrations/**`
- Modify: `backend/src/app/worker/**`
- Test: `backend/tests/test_app_factory.py`
- Test: `backend/tests/test_chat_endpoint_dependencies.py`
- Test: `backend/tests/test_chat_model_factory_llamacpp.py`
- Test: `backend/tests/test_model_config_service_llamacpp.py`

- [ ] Step 1: 先锁定入口行为测试，必要时补最小化回归断言
- [ ] Step 2: 运行目标测试，确认基线
- [ ] Step 3: 移除确认无用的 helper、重复导入、遗留桥接
- [ ] Step 4: 重跑目标测试
- [ ] Step 5: 更新清单并提交里程碑

### Task 4: agent/tool/search/prompt 层清理

**Files:**
- Modify: `backend/src/app/agents/**`
- Modify: `backend/src/app/search/**`
- Modify: `backend/src/app/prompts/**`
- Test: `backend/tests/test_kb_chat_agentic_graph_helper_modules.py`
- Test: `backend/tests/test_kb_chat_trace_display_contract_helpers.py`
- Test: `backend/tests/test_query_rewrite_helper_modules.py`
- Test: `backend/tests/test_web_search_helper_modules.py`

- [ ] Step 1: 先核查图节点装配、工具注册、提示词加载路径
- [ ] Step 2: 删除已废弃的 agent helper 或重复 contract，仅在证据充分时修改模板文件
- [ ] Step 3: 重跑该层相关测试
- [ ] Step 4: 更新清单并提交里程碑

### Task 5: service 层非 research 清理

**Files:**
- Modify: `backend/src/app/services/general_chat_service*.py`
- Modify: `backend/src/app/services/ingestion_*.py`
- Modify: `backend/src/app/services/retrieval_*.py`
- Modify: `backend/src/app/services/export*.py`
- Modify: `backend/src/app/services/parsing/**`
- Modify: `backend/src/app/services/semantic_cache/**`
- Test: `backend/tests/test_general_chat_service_helper_binding.py`
- Test: `backend/tests/test_general_chat_service_helper_modules.py`
- Test: `backend/tests/test_ingestion_batch_service_helper_modules.py`
- Test: `backend/tests/test_retrieval_service_helper_modules.py`

- [ ] Step 1: 优先清理 helper/contract/execution/runtime 多文件拆分后残留的桥接代码
- [ ] Step 2: 对外暴露接口保持不变，只收缩内部重复实现
- [ ] Step 3: 重跑对应 helper 模块测试
- [ ] Step 4: 更新清单并提交里程碑

### Task 6: research 运行时与报告链路清理

**Files:**
- Modify: `backend/src/app/services/deep_research_runtime.py`
- Modify: `backend/src/app/services/research_*.py`
- Modify: `backend/src/app/services/research_service*.py`
- Modify: `backend/src/app/services/research_runtime_*.py`
- Test: `backend/tests/test_research_agent_runs_removal.py`
- Test: `backend/tests/test_research_artifact_normalization.py`
- Test: `backend/tests/test_research_clarification_policy.py`
- Test: `backend/tests/test_research_runtime_context_management.py`
- Test: `backend/tests/test_research_runtime_factory.py`
- Test: `backend/tests/test_research_runtime_helper_modules.py`
- Test: `backend/tests/test_research_runtime_report_enrichment.py`
- Test: `backend/tests/test_research_service_contracts_module.py`
- Test: `backend/tests/test_research_service_execution_helpers.py`
- Test: `backend/tests/test_research_service_finalization_contract.py`
- Test: `backend/tests/test_research_service_session_ops_module.py`

- [ ] Step 1: 先确认 runtime/report/artifacts 单一事实源
- [ ] Step 2: 删除 research service / runtime 拆分后的死路径、重复映射、遗留镜像逻辑
- [ ] Step 3: 运行 research 相关回归测试
- [ ] Step 4: 更新清单并提交里程碑

### Task 7: tests、迁移与最终复审

**Files:**
- Modify: `backend/tests/**`
- Review: `backend/alembic/**`
- Review: `backend/pyproject.toml`
- Review: `backend/alembic.ini`

- [ ] Step 1: 审查测试文件本身是否存在已过期、仅服务于旧实现的残留断言
- [ ] Step 2: 对 Alembic 迁移只做“审查和记录”，除非证据极强，否则不删迁移
- [ ] Step 3: 运行本次改动直接对应的 pytest 集合与必要的 `pyright -p backend/pyproject.toml`
- [ ] Step 4: 请求代码审查并修正问题
- [ ] Step 5: 准备分支收尾
