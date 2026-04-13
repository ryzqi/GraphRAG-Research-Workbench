# 配置与 Secrets Runbook

## 适用范围

- `scripts/start_all.ps1`
- `scripts/verify_quickstart.ps1`
- `infra/up.ps1`
- `infra/podman-compose.yml`

以上脚本和模板已经收敛为单一 compose 事实源。不要再创建 `base/dev/prod overlay` 副本，也不要把示例口令、loopback URL、宿主机代理 IP 写回共享文件。

## 配置分层

### 1. Deploy config

- 后端 deploy config：`.env` 中的 `CORE__* / STORAGE__* / WEB_SEARCH__* / HTTP_CLIENT__*`
- 本地基础设施 dev profile：`infra/env/dev.env.example`
- 生产基础设施 profile：`infra/env/prod.env.example`
- 基础设施编排事实源：`infra/podman-compose.yml`

### 2. Policy config

- 搜索 / research / 前端 runtime 行为：`backend/src/app/config/policies/*.yaml`

### 3. Contract manifest

- runtime / workspace / provider descriptor：后端源码内的单点 manifest

## 本地开发

1. 复制根目录 `.env.example` 为 `.env`，补齐后端与前端公开地址、外部服务密钥。
2. 如需覆盖本地基础设施默认值，复制 `infra/env/dev.env.example` 为 `infra/env/dev.env` 再修改。
3. 运行本地基础设施：

```powershell
pwsh -ExecutionPolicy Bypass -File .\infra\up.ps1
```

切换到单一 compose 后，基础设施数据改为命名卷持久化；旧 `infra/data/*` 绑定目录不会自动迁移到新卷，如需保留历史本地数据，请先备份或手动导入。

4. 运行一键开发编排：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

5. 做本地 quickstart 验收：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1 -SkipInfra
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1
```

## 生产部署

推荐方式：

```powershell
Set-Location 'F:\毕设\code\infra'
Copy-Item .\env\prod.env.example .\env\prod.env
podman compose -f .\podman-compose.yml --env-file .\env\prod.env config
podman compose -f .\podman-compose.yml --env-file .\env\prod.env up -d
```

上线前必须把 `prod.env` 中的占位值替换为真实部署值，并通过 secrets manager 或部署平台注入。
若 backend / worker / frontend 不在同一 compose 网络内运行，根目录 `.env` 也必须同步改成外部可达的服务地址。

## Secrets 注入原则

### 允许

- 平台环境变量注入
- 容器 secret mount / file secret
- 外部 secret sync 到运行环境

### 禁止

- 把真实密钥、默认口令、办公网代理地址直接写进仓库
- 让前端 `NEXT_PUBLIC_*` 暴露 secrets
- 把 feature flags 当作 secrets manager

## Feature Flags 与 Secrets 的边界

- Feature flag 平台负责行为开关、灰度、审计、RBAC。
- Secrets manager 负责密钥、口令、轮换、TTL、最小权限。
- 同一值如果是认证材料，就必须放在 secrets manager，不放在 flag 平台。

## 迁移顺序

1. 先发布后端 typed settings / policy / runtime contract 代码。
2. 为前端与脚本补齐公开地址变量：
   - `NEXT_PUBLIC_API_BASE_URL`
   - `BACKEND_PUBLIC_BASE_URL`
   - `FRONTEND_PUBLIC_BASE_URL`
3. 将本地与单机生产基础设施统一到 `infra/podman-compose.yml`。
4. 将根目录 `.env` 中数据库 / Redis / MinIO / SearXNG 地址分别对齐到：
   - 同 compose 网络：`postgres` / `redis` / `minio` / `searxng`
   - 宿主机运行应用：`localhost + infra/env/*.env` 暴露端口
5. 启用 `scripts/check_hardcoded_config.ps1`、`frontend/scripts/check-public-runtime-config.mjs` 与后端测试守卫。

## 回滚策略

- 若生产 overlay 配置错误，优先回滚 `prod.env` 或平台环境变量，不回滚代码层 policy/contract。
- 若 provider descriptor 或 runtime config 新契约引发前端问题，回滚前端发布版本并保留后端守卫。
- 若 SearXNG/基础设施 profile 变更引发连通性问题，回退到上一个已验证的 `podman-compose.yml + prod.env` 组合。

## 需要轮换的 Secrets

- `POSTGRES_PASSWORD`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- `SEARXNG_SECRET`
- `CORE__EMBEDDING_API_KEY`
- `CORE__MODEL_CONFIG_KMS_KEY`

## 旧变量与旧路径清理

- 已移除脚本内 `VITE_API_BASE_URL` 兼容映射。
- 不再接受 provider registry 内置 local provider `default_base_url`。
- 不再接受基础设施模板中的默认口令和固定代理 IP。
- 不再接受 `podman-compose.base.yml + podman-compose.dev.yml/prod.example.yml` layering。

## 审计命令

```powershell
pwsh -NoProfile -File .\scripts\check_hardcoded_config.ps1
Set-Location .\frontend; npm run lint
Set-Location ..\backend; $env:UV_CACHE_DIR='F:\毕设\code\.uv-cache'; uv run pytest tests\test_no_duplicate_provider_registry.py tests\test_policy_manifest_integrity.py -q
```
