# Backend 清理发现记录

## 基线

- 范围事实源：`git ls-files backend`
- 当前统计：
  - `backend/src`: 336 个文件
  - `backend/tests`: 24 个文件
  - `backend/alembic`: 16 个文件
  - 根文件：`backend/pyproject.toml`、`backend/alembic.ini`
- 当前分支基线：待切出专用清理分支

## 高风险动态/注册点

- `backend/src/app/api/v1/api.py`
  - FastAPI 路由统一注册点；删 endpoint 前必须确认未在此处 `include_router`
- `backend/src/app/worker/celery_app.py`
  - Celery `include` 列表是 worker 任务注册点；删 task 模块前必须先核查此处
- `backend/src/app/bootstrap/lifespan.py`
  - 应用启动和关闭边界；初始化项不可凭“暂时没看到引用”删除
- `backend/src/app/prompts/loader.py`
  - 提示词模板加载边界；模板 YAML 是否冗余不能只看 Python 静态引用
- `backend/src/app/integrations/mcp_adapters.py`
  - 可能存在字符串驱动适配关系；删除前要核查配置与调用方
- `backend/src/app/integrations/model_runtime_config.py`
  - 运行时模型配置入口；与 provider、health probe、factory 互相耦合
- `backend/src/app/services/research_runtime_factory.py`
  - Deep research backend 路由与工具装配边界

## 大文件热点

- `backend/src/app/agents/kb_chat_agentic/preprocess.py` 2107 行
- `backend/src/app/agents/kb_chat_agentic/answer_subgraph.py` 1876 行
- `backend/src/app/agents/kb_chat_agentic/reflection.py` 1725 行
- `backend/src/app/services/general_chat_service_execution.py` 1194 行
- `backend/src/app/services/chunking.py` 900 行
- `backend/src/app/agents/retrieval_subgraph.py` 794 行
- `backend/src/app/services/query_rewrite_planning_ops.py` 768 行
- `backend/src/app/services/research_service.py` 735 行
- `backend/src/app/core/settings.py` 720 行
- `backend/src/app/services/kb_chat_service_stream_protocol.py` 718 行

## 当前策略

- 先判“是否真无用”，再决定“删还是保留”。
- 对大文件，优先找：
  - 已废弃 helper
  - 重复 contract / serializer / mapper
  - 仅为历史兼容保留的分支
  - 已拆模块后残留的桥接函数
- 对 `alembic/versions`，默认高度保守：
  - 没有清晰迁移链路证据，不做删除
- 对 `prompts/templates`，默认先做“加载路径核查”，不是先删 YAML
- 对 `tests`，既是行为基线，也是“遗留测试是否仍对应现存行为”的审查对象

## 来自记忆的协作偏好

- 用户从“审查冗余”进入“开始清理”时，可直接执行，不需要额外规划回合。
- 完成判据必须是 direct verification，不能只凭分析声称清理完成。
