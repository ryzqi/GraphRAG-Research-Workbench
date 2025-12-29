# 多知识库 + 多智能体协作知识代理系统

本仓库为毕业设计代码与演示脚手架，目标是实现：多知识库隔离与联合检索、可追溯证据清单、多智能体协作/深度研究、对比评测与导出复现。

- 规格与设计文档：`specs/001-multi-kb-agent-collab/`
- 快速开始（强烈建议先读）：`specs/001-multi-kb-agent-collab/quickstart.md`
- API 契约（OpenAPI）：`specs/001-multi-kb-agent-collab/contracts/openapi.yaml`

## 本地运行（Windows）

### 1) 启动基础依赖（Podman）

- 复制 `.env.example` 为 `.env` 并按需修改
- 在仓库根目录运行：

```powershell
.\infra\up.ps1
```
### 2) 启动后端（FastAPI）

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 文档：`http://localhost:8000/docs`
- 健康检查：`GET http://localhost:8000/api/v1/health`

### 3) 启动 Worker（Celery）

```bash
cd backend
uv run celery -A app.worker.celery_app worker --loglevel=INFO --pool=solo
```

### 4) 启动前端（React + Vite）

```bash
cd frontend
npm install
npm run dev
```
