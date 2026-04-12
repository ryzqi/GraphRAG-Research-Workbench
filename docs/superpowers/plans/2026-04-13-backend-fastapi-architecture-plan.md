# Backend FastAPI 架构收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变功能的前提下，把后端收敛到更符合 FastAPI service architecture 的最小必要形态。

**Architecture:** 先收拢 app resources 与 service provider，让路由退出装配职责；再对高耦合热点引入最小 repository 层，最后用文档和测试固定新的边界。

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, pytest, uv

---

### Task 1: 固化设计基线

**Files:**
- Create: `F:\毕设\code\docs\superpowers\specs\2026-04-13-backend-fastapi-architecture-design.md`
- Create: `F:\毕设\code\docs\superpowers\plans\2026-04-13-backend-fastapi-architecture-plan.md`

- [ ] **Step 1: 写设计文档**
- [ ] **Step 2: 自检无占位符、范围清晰**
- [ ] **Step 3: 提交设计文档**

### Task 2: 建立应用资源与 API 依赖装配层

**Files:**
- Create: `F:\毕设\code\backend\src\app\bootstrap\app_resources.py`
- Create: `F:\毕设\code\backend\src\app\api\dependencies\app_resources.py`
- Create: `F:\毕设\code\backend\src\app\api\dependencies\services.py`
- Modify: `F:\毕设\code\backend\src\app\bootstrap\lifespan.py`
- Modify: `F:\毕设\code\backend\src\app\api\v1\endpoints\research.py`
- Modify: `F:\毕设\code\backend\src\app\api\v1\endpoints\system.py`
- Modify: `F:\毕设\code\backend\src\app\api\v1\endpoints\chats.py`
- Modify: `F:\毕设\code\backend\src\app\api\v1\endpoints\extensions.py`
- Modify: `F:\毕设\code\backend\src\app\api\v1\endpoints\exports.py`
- Modify: `F:\毕设\code\backend\src\app\api\v1\endpoints\ingestion_batches.py`
- Modify: `F:\毕设\code\backend\tests\test_app_factory.py`
- Modify: `F:\毕设\code\backend\tests\test_chat_endpoint_dependencies.py`

- [ ] **Step 1: 先写/改失败测试，要求新依赖层存在且 endpoint 不再手工装配 service**
- [ ] **Step 2: 运行对应测试，确认先红**
- [ ] **Step 3: 实现 `AppResources` 与 service providers，并改写 endpoint**
- [ ] **Step 4: 再跑测试确认转绿**
- [ ] **Step 5: 提交 M1**

### Task 3: 为 research/extensions/system 提炼最小 repository 层

**Files:**
- Create: `F:\毕设\code\backend\src\app\repositories\__init__.py`
- Create: `F:\毕设\code\backend\src\app\repositories\research_session_repository.py`
- Create: `F:\毕设\code\backend\src\app\repositories\extension_repository.py`
- Create: `F:\毕设\code\backend\src\app\repositories\queue_health_repository.py`
- Modify: `F:\毕设\code\backend\src\app\services\research_service.py`
- Modify: `F:\毕设\code\backend\src\app\services\extension_service.py`
- Modify: `F:\毕设\code\backend\src\app\services\queue_health_service.py`
- Modify: `F:\毕设\code\backend\src\app\api\dependencies\services.py`
- Modify: `F:\毕设\code\backend\tests\test_research_service_session_ops_module.py`
- Modify: `F:\毕设\code\backend\tests\test_chat_endpoint_dependencies.py`
- Create: `F:\毕设\code\backend\tests\test_architecture_service_providers.py`

- [ ] **Step 1: 先写/改失败测试，要求 service 通过 repository/provider 获取持久化依赖**
- [ ] **Step 2: 运行对应测试，确认先红**
- [ ] **Step 3: 实现 repository 并重连 service/provider**
- [ ] **Step 4: 再跑测试确认转绿**
- [ ] **Step 5: 提交 M2**

### Task 4: 文档与最终架构验收

**Files:**
- Modify: `F:\毕设\code\docs\architecture.md`
- Modify: `F:\毕设\code\findings.md`
- Modify: `F:\毕设\code\progress.md`
- Modify: `F:\毕设\code\task_plan.md`

- [ ] **Step 1: 更新架构文档与规划文件**
- [ ] **Step 2: 运行本次改动直接对应的测试/静态检查**
- [ ] **Step 3: 确认 git diff 只包含架构收敛**
- [ ] **Step 4: 提交 M3**
