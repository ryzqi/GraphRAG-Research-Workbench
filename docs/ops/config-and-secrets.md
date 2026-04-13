# 配置与 Secrets Runbook

## 适用范围

- `scripts/start_all.ps1`
- `scripts/verify_quickstart.ps1`
- `infra/up.ps1`
- `infra/podman-compose.base.yml`
- `infra/podman-compose.dev.yml`
- `infra/podman-compose.prod.example.yml`

以上脚本和模板已经按 `dev-only quickstart` 与 `production profile` 分层。不要再把示例口令、loopback URL、宿主机代理 IP 写回共享文件。

## 配置分层

### 1. Deploy config

- 后端 deploy config：`.env` 中的 `CORE__* / STORAGE__* / WEB_SEARCH__* / HTTP_CLIENT__*`
- 本地基础设施 dev profile：`infra/env/dev.env.example`
- 生产基础设施 profile：`infra/env/prod.env.example`

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

生产环境不要直接使用 `infra/podman-compose.yml` 或 `infra/podman-compose.dev.yml`。

推荐方式：

```powershell
Set-Location 'F:\毕设\code\infra'
Copy-Item .\env\prod.env.example .\env\prod.env
podman compose -f .\podman-compose.base.yml -f .\podman-compose.prod.example.yml --env-file .\env\prod.env config
```

上线前必须把 `prod.env` 中的占位值替换为真实部署值，并通过 secrets manager 或部署平台注入。

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
3. 将本地基础设施改为 `podman-compose.base.yml + podman-compose.dev.yml`。
4. 生产环境改为 `podman-compose.base.yml + podman-compose.prod.example.yml`。
5. 启用 `scripts/check_hardcoded_config.ps1`、`frontend/scripts/check-public-runtime-config.mjs` 与后端测试守卫。

## 回滚策略

- 若生产 overlay 配置错误，优先回滚 `prod.env` 或平台环境变量，不回滚代码层 policy/contract。
- 若 provider descriptor 或 runtime config 新契约引发前端问题，回滚前端发布版本并保留后端守卫。
- 若 SearXNG/基础设施 profile 变更引发连通性问题，回退到上一个已验证的 `prod.env` 与 overlay 组合。

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

## 审计命令

```powershell
pwsh -NoProfile -File .\scripts\check_hardcoded_config.ps1
Set-Location .\frontend; npm run lint
Set-Location ..\backend; $env:UV_CACHE_DIR='F:\毕设\code\.uv-cache'; uv run pytest tests\test_no_duplicate_provider_registry.py tests\test_policy_manifest_integrity.py -q
```
