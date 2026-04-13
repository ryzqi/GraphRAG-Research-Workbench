# 硬编码审计与生产级优化建议

日期：2026-04-13

## 目标

- 定位仓库内会影响生产行为的硬编码文件，并以 `backend/src/app/search/web/query_rewrite.py` 为样本扩展排查。
- 区分“应尽快外置/收敛”的硬编码与“暂可接受的内部协议常量”。
- 基于 Agent Reach 的外部资料，给出适合本仓库的生产级优化方向。

## 判定标准

- 计入本次审计：
  - 会随部署环境变化但被写死在代码中的 URL、主机、端口、凭据、provider 顺序、轮询/缓存/重试窗口。
  - 会直接影响检索、研究、路由、评分、澄清、质量门禁的策略词表、阈值、权重、默认理由文本。
  - 同一规则在后端、runtime、前端多处重复定义，违反单一事实源。
- 暂不计入主清单：
  - 测试、lockfile、README 示例、纯 UI 尺寸常量、枚举/schema 边界。
  - 明显属于内部稳定协议且已集中定义、短期不需要跨环境切换的常量，但会在“低优先级命中”里保留。

## 高优先级硬编码源文件

### 1. 搜索 / 检索 / 政策启发式

- `backend/src/app/search/web/query_rewrite.py`
  - 写死了 freshness 关键词、`langchain -> site:docs.langchain.com` 特判、固定年份 `2026`。
  - 这是典型的策略硬编码；一旦年份变化、目标站点变化、关键词语言变化，就需要发版改代码。
- `backend/src/app/search/web/rerank.py`
  - 写死了低质量域名后缀、高权威域名后缀，以及 `0.9 / 0.08 / 0.45 / 0.12 / 0.35` 等评分权重。
  - 这是生产排序策略，不应散落在代码里。
- `backend/src/app/search/web/enrichment.py`
  - 写死了低质量域名后缀、`_SNIPPET_MIN_LENGTH = 180`、默认 `top_k = 2`、默认 provider 名 `jina_reader`。
  - 属于正文补读策略，应进入集中配置。
- `backend/src/app/search/web/fusion.py`
  - 写死了 `_RRF_K = 60` 和 provider 权重 `{tavily: 1.0, searxng: 0.85}`。
  - 这是召回融合策略，不应靠源码常量长期维护。
- `backend/src/app/services/query_rewrite_text.py`
  - 写死了指代词表、比较/分类/故障排查关键词、`_COREF_CONFIDENCE_THRESHOLD = 0.72`、默认澄清问题与默认理由文本。
  - 语义判断与用户文案耦合在代码里，后续很难做版本化、灰度和 A/B。
- `backend/src/app/services/query_rewrite_contracts.py`
  - 写死了 `DECOMPOSITION_MAX_SUB_QUERIES = 5`、`MULTI_QUERY_FIXED_VARIANTS = 3`、`HYDE_NUM_HYPOTHESES = 5`、重试原因与重试次数。
  - 这些是检索编排预算，不应散布为裸常量。
- `backend/src/app/services/research_query_mesh.py`
  - 写死了 `DEFAULT_REQUIRED_WEB_PROVIDERS`、复杂度到 provider 数量的映射、复杂度到唯一来源数量的映射。
  - 属于 research coverage gate 核心策略。
- `backend/src/app/services/web_search_status_service.py`
  - 写死了 provider 顺序、缓存 TTL、Jina 健康检查 URL 和固定 probe query。
  - 既有环境策略，也有探活策略。
- `backend/src/app/agents/tools/web_search_utils.py`
  - 写死了 `TAVILY_BASE_URL`、降级条件、HTTP 状态码集合与降级后的 payload。
  - 属于外部 provider 行为策略，应该被注册表或 typed config 承载。

### 2. 运行时 / provider / 环境默认值

- `backend/src/app/core/settings.py`
  - 集中包含大量环境默认值：`localhost/127.0.0.1`、数据库/Redis/MinIO 默认连接、`minioadmin`、`REPLACE_ME`、`https://r.jina.ai`、`https://api.openai.com`、各类 timeout/retry/poll/research gate 阈值。
  - 该文件已经是“集中点”，但当前问题是默认值过多、过强，会把 dev 习惯带入 prod。
- `backend/src/app/integrations/chat_model_factory.py`
  - 写死了 provider 默认重试、NVIDIA 超时上限、Ollama 默认 URL、thinking 默认行为。
  - 运行时 provider 行为不应由工厂内部常量决定。
- `backend/src/app/integrations/model_runtime_config.py`
  - 写死了 `_PROVIDER_PRIORITY`、fallback active provider=`openai`、thinking 默认值与 level。
  - 与其他 provider 配置文件重复定义，违反单一事实源。
- `backend/src/app/services/model_config_service.py`
  - 再次写死 provider 顺序、llama.cpp 默认 URL、thinking 默认值。
  - 与 `model_runtime_config.py`、前端模型配置页同时维护，容易漂移。
- `backend/src/app/services/research_planner.py`
  - 写死 `_DEFAULT_SCOPER_STRUCTURED_METHOD = "function_calling"` 与 Ollama 特例 `json_mode`。
  - 属于模型能力路由策略，应进入 provider capability registry。

### 3. Deep Research runtime 路径与上下文装配

- `backend/src/app/services/deep_research_runtime.py`
  - 写死 `_DEFAULT_WORKSPACE_CONTEXT_DOCS`，把虚拟路径与仓库磁盘文件一一绑定。
  - 这是 runtime 上下文装配规则，应集中在一个 manifest，而不是在执行代码里散放。
- `backend/src/app/services/research_runtime_types.py`
  - 写死 `/workspace/`、`/scratch/`、`/plans/`、`/memories/`、`/skills/`、`/scratch/research-spill/`、`max_inline_chars=6000`、`stream version=v2`。
  - 这类常量更接近协议层，短期可保留，但应视为 runtime contract 而不是任意散落字符串。
- `backend/src/app/services/research_runtime_context.py`
  - 写死了 `RUNTIME_CONTEXT_GUIDE_PATH`、请求上下文路径、优先读取路径规则。
  - 属于 runtime contract，建议与 layout manifest 合并。
- `backend/src/app/services/research_runtime_workspace.py`
  - 写死默认 memory 路径、`file://` URI 方案、context 文件路径、runtime-memory 模板文本。
  - 既有路径硬编码，也有模板硬编码。
- `backend/src/app/services/research_workspace_files.py`
  - 写死 workspace/scratch 文件布局与编号路径。
  - 这是 contract 级硬编码，建议保留单点，但不能继续在其他文件重复。

### 4. 前端生产行为与后端重复定义

- `frontend/src/services/http.ts`
  - 写死了 `NEXT_PUBLIC_API_BASE_URL` 缺失时回退到 `http://127.0.0.1:8000`，并强行把 `localhost` 改写为 `127.0.0.1`。
  - 生产环境若缺配置，当前行为是“猜 dev 地址”，不是 fail-fast。
- `frontend/src/services/sse.ts`
  - 连接失败提示里写死 `http://127.0.0.1:8000`。
  - 属于前端文案层的环境硬编码。
- `frontend/src/views/ModelConfigPage.tsx`
  - 再次写死 provider 列表、provider label、各种 base URL placeholder。
  - 与后端 provider 顺序/默认 URL 重复维护。
- `frontend/src/constants/runtimeDefaults.ts`
  - 写死了 polling interval、SSE fallback step、retry multiplier、export poll 尝试次数。
  - 这些会直接影响前端负载与用户等待体验，应做成集中运行时配置。
- `frontend/src/constants/formDefaults.ts`
  - 写死默认 provider=`openai`、thinking=`high`、extension transport=`http`、auth=`none`。
  - 属于产品默认策略，不应只藏在前端。
- `frontend/src/utils/urlValidation.ts`
  - 下载域名白名单只允许 `localhost` 和 `127.0.0.1`。
  - 这在生产几乎不可用，而且属于安全策略硬编码。
- `frontend/src/services/serverPrefetchCache.ts`
  - 写死 `revalidate = 30s`。
  - 应与后端缓存/刷新策略统一，而不是前端单独裸写。

### 5. 运维脚本 / 基础设施 / 示例配置

- `scripts/start_all.ps1`
  - 写死 API 地址、`uvicorn` 启动命令、localhost/127.0.0.1 规则、旧变量兼容逻辑。
  - 适合拆成环境 profile + 参数化脚本。
- `scripts/verify_quickstart.ps1`
  - 写死 health check 地址、docs 地址、后端启动命令。
  - 属于验收路径硬编码。
- `.env.example`
  - 写死了大量 dev 默认值与示例口令，如 `SEARXNG_BASE_URL`、`mkb:mkb`、`localhost`、`JINA_READ_BASE_URL`。
  - 这类示例文件可以存在，但应明确区分“示例占位符”和“生产禁止默认”。
- `backend/alembic.ini`
  - 写死数据库连接串。
  - 数据库连接不应在迁移配置中以真实口令样式常驻。
- `infra/podman-compose.yml`
  - 写死 `NO_PROXY`、`SEARXNG_BASE_URL` 默认值。
  - 基础设施模板里允许默认值，但生产 overlay 应独立于开发 compose。
- `infra/searxng/config/settings.yml`
  - 写死 `base_url: http://127.0.0.1:18080/`，还出现固定代理地址示例。
  - 需要通过环境覆盖或模板渲染，而不是文件内固定。

## 单一事实源冲突

- provider 顺序/默认值重复定义在：
  - `backend/src/app/services/model_config_service.py`
  - `backend/src/app/integrations/model_runtime_config.py`
  - `frontend/src/views/ModelConfigPage.tsx`
- 澄清理由与 query plan 理由重复定义在：
  - `backend/src/app/services/query_rewrite_text.py`
  - `backend/src/app/agents/kb_chat_trace_display_shared.py`
- 多实体判断关键词重复定义在：
  - `backend/src/app/services/query_rewrite_text.py`
  - `backend/src/app/agents/kb_chat_agentic/reflection.py`

结论：当前最大的问题不是“有常量”，而是“同一策略在多层重复写死”，这会直接破坏单一事实源。

## 低优先级扫描命中

以下文件也命中了硬编码模式，但当前更接近协议常量、内部实现细节或低风险产品默认，建议放在第二阶段再清理：

- backend
  - `backend/src/app/agents/kb_chat_memory.py`
  - `backend/src/app/services/ingestion_batch_service_contracts.py`
  - `backend/src/app/services/kb_chat_service_contracts.py`
  - `backend/src/app/services/retrieval_service_contracts.py`
  - `backend/src/app/utils/token_counter.py`
  - `backend/src/app/integrations/milvus_client.py`
  - `backend/src/app/schemas/extensions.py`
  - `backend/src/app/integrations/mcp_adapters.py`
- frontend
  - `frontend/src/views/ExtensionsPage.tsx`
  - `frontend/src/services/knowledgeBaseDetailLayout.ts`
  - `frontend/src/services/materialChunkBrowser.ts`
  - `frontend/src/config/bundle-budgets.json`
- 不纳入本次主清单
  - `tests/`、`*.test.*`、迁移里的历史示例数据、`README.md` 示例命令、lockfile。

## Agent Reach 调研结论

### 1. 环境相关配置必须从代码中剥离

- Twelve-Factor `Config` 的核心要求是：凡是会在不同 deploy 间变化的配置，都不应写死在代码里，应通过环境变量独立管理。
- 直接映射到本仓库：
  - `localhost/127.0.0.1`、第三方 `base_url`、provider 默认 URL、CORS 源、轮询窗口、probe URL 都不应靠代码默认值维持。
  - 如果一个值在 prod/staging/dev 之间可能不同，就不应以源码常量作为唯一入口。

### 2. Secrets 不要放在源码、默认值或前端可见配置里

- HashiCorp 与 OWASP 都明确把 hard-coded secrets 视为反模式。
- 生产级做法：
  - 使用集中式 secrets manager 或云原生 secret store。
  - 使用动态凭据、TTL、自动 rotation、最小权限、审计日志。
  - CI/CD 使用 OIDC/JWT 或平台身份，不使用长期静态 token。
- 直接映射到本仓库：
  - `minioadmin`、`REPLACE_ME`、迁移配置里的连接串样式默认值都应移除或改成强制显式配置。

### 3. Feature Flag 应该替代“策略开关散落在代码里”，但不能承载 secrets

- Unleash 与 OpenFeature 的共同点：
  - flag 应作为运行时控制平面，而不是源码里的 if/else 常量集合。
  - 生产改 flag 要有 RBAC、审批、审计日志、环境隔离。
  - 客户端 flag 只负责 UX，不负责授权；真正的检查必须在服务端。
- 直接映射到本仓库：
  - query rewrite、research gate、provider fallback、前端 polling/revalidate 这类会频繁调优的策略，应逐步迁移到 flag/config registry。
  - 但 `API key`、连接串、token 不能放进 feature flag 平台。

### 4. 配置不仅要外置，还要可验证、可审计、可灰度

- Twelve-Factor 解决的是“不要写死”。
- HashiCorp / OWASP / Unleash 进一步要求：
  - 配置/凭据要可轮换。
  - 访问要可审计。
  - 变更要有审批或至少有变更记录。
  - 运行时要支持逐步发布，而不是代码发版。
