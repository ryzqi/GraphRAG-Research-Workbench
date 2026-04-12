# Backend FastAPI 架构收敛设计

## 背景

目标是审查 `backend/src/app` 是否满足 `fastapi-service-architecture` 的核心原则，并在不修改功能、不改变对外契约的前提下，对当前后端做最小必要的架构拆分与职责收敛。

本设计只处理架构、分层、依赖注入、事务边界与目录职责，不处理业务规则优化，也不引入兼容层。

## 审查结论

### 已满足项

- 入口与引导已分离：`main.py` 仅负责 settings / logging / app factory。
- 使用了 `lifespan`：`bootstrap/app_factory.py` + `bootstrap/lifespan.py` 已符合当前 FastAPI 生命周期模式。
- API 路由统一挂载到 `/api/v1`，整体 HTTP 前缀一致。
- `AsyncSession` 依赖已经集中在 `api/deps.py` 与 `db/session.py`。
- `research` 域已有部分“存储职责拆分”雏形：`ResearchArtifactStore`、`ResearchEventStore`。

### 未满足项

1. 路由层仍承担装配职责
   - 多个 endpoint 直接 `service = XxxService(db)`。
   - `research`、`chat`、`system` 端点直接读取 `request.app.state.*` 并自行拼装 service。
   - 这导致 HTTP 层知道了太多运行时资源细节。

2. 持久化边界不清
   - 当前仓库不存在 `repositories/` 目录。
   - 多数 service 直接持有 `AsyncSession`，同时负责查询、提交、回滚与业务编排。
   - `ExtensionService`、`KnowledgeBaseService`、`QueueHealthService`、`ResearchService` 等都同时包含 orchestration 与 persistence 细节。

3. 事务边界风格不一致
   - 一部分提交在 endpoint 中完成。
   - 一部分提交在 service 中完成。
   - worker 任务中又有一套显式 commit/rollback。
   - 当前没有清晰、稳定的“谁拥有事务边界”规则。

4. API 依赖注入尚未形成稳定模式
   - 只有 `AsyncSessionDep` 是统一依赖。
   - runtime 资源、service factory、应用资源读取没有集中到单一依赖模块。

## 方案比较

### 方案 A：只做命名和目录整理

- 做法：保持现有构造方式，只新增文档或轻度重命名。
- 优点：改动最小。
- 缺点：核心问题不变，路由仍旧过度装配，service 仍旧直连持久化，无法实质满足 skill 原则。

### 方案 B：最小必要分层收敛

- 做法：集中 app resources / service providers；为高耦合热点新增最小 repository；保留大多数 service 作为 orchestration 层；不盲目引入 domain/use_cases。
- 优点：改动可控、收益明确、符合“选择最小足够结构”的原则。
- 缺点：不会在一次迭代内把所有 service 都迁移到完全一致的形态。

### 方案 C：全量引入 domain/use_cases/ports

- 做法：对整个 backend 进行完整 Clean Architecture 迁移。
- 优点：理论上一致性最高。
- 缺点：范围过大，风险明显高于收益，也不符合“仅做最小必要架构收敛”的约束。

## 推荐方案

采用方案 B。

原因：

- 当前后端已经具备单体 FastAPI + Celery + 多基础设施依赖的复杂度，但还没有达到“全域 ports/use_cases”才有收益的程度。
- 最大痛点不是“缺少 domain object”，而是“装配逻辑散落在路由层”和“service 直接兼任持久化层”。
- 先把依赖注入、装配边界、代表性热点 repository 化，能在不动业务功能的前提下得到最大的架构收益。

## 目标架构形状

### 目录形状

在保留现有目录主干的前提下，补齐最小必要结构：

```text
backend/src/app/
  api/
    deps.py
    dependencies/
      app_resources.py
      services.py
  bootstrap/
    app_factory.py
    lifespan.py
    app_resources.py
  repositories/
    extension_repository.py
    queue_health_repository.py
    research_session_repository.py
  services/
    ...
```

### 依赖方向

- `api/` 只依赖依赖提供器、schemas、services/use cases。
- `services/` 依赖 `repositories/`、stores、integrations。
- `repositories/` 只依赖 `models/`、SQLAlchemy、session。
- `bootstrap/` 负责创建并注册 app resources，不承载业务逻辑。

### 应用资源边界

- 将 `app.state.*` 的分散字段读取收拢为一个类型化 `AppResources` 容器。
- API 侧只通过依赖函数读取 `AppResources`，不再在各 endpoint 内直接拼接运行时资源。

### 拆分范围

本轮仅对以下高价值热点做 repository 化：

- `research`：会话聚合读取与基础持久化边界。
- `extensions`：典型 CRUD + 外部集成读取，适合抽出 repository。
- `system queue health`：将 DB 查询与 infra 检查拆开。

## 里程碑

### M0 现状审查与设计定稿

- 写入设计文档与实现计划。
- 不改业务代码。

### M1 应用装配与依赖注入边界收敛

- 引入 `bootstrap/app_resources.py`。
- 引入 `api/dependencies/app_resources.py`、`api/dependencies/services.py`。
- 把 `research`、`chat`、`system`、`extensions`、`exports`、`ingestion_batches` 等 endpoint 的 service 装配迁到依赖层。
- 路由仅保留 HTTP 参数解析、header 读取、返回映射、stream disconnect 检查。

### M2 高耦合热点 repository 化

- 新增 `repositories/`。
- 让 `ExtensionService`、`QueueHealthService`、`ResearchService` 在最小范围内改为依赖 repository / store，而不是直接混写 SQLAlchemy 查询。
- 不引入额外兼容层，不做功能重写。

### M3 文档与测试收敛

- 更新 `docs/architecture.md`。
- 为新的依赖装配与 repository 边界补充测试。
- 做针对性验证，并完成最终审查。

## 非目标

- 不重写全部 service。
- 不引入全量 `domain/`、`use_cases/`、`ports/`。
- 不改变 API 路径、请求体、响应体、状态码。
- 不修改 runtime / worker 的业务行为。
