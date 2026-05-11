# 多知识库 + 多智能体协作知识代理系统

这是一个面向多知识库问答与 Deep Research 场景的开源项目。目标不是只做一个“能聊天”的 RAG Demo，而是把下面几类能力放到同一套可复现系统里：

- 多知识库隔离与联合检索
- 可追溯证据清单与引用编号
- KB Chat 的 agentic 检索编排
- Deep Research 的多阶段研究流水线
- 会话级上下文、工件与展示快照统一管理

项目采用前后端分离结构：前端负责交互、可视化与工件消费；后端负责解析、分块、索引、检索、研究运行时与导出。

## Features

- 多知识库：每个知识库维护独立 `index_config`，支持隔离检索，也支持同一问题跨库检索。
- 多种分块策略：支持 `query_dependent_multiscale`、`max_min_semantic`、`parent_child`、`markdown_heading`。
- 混合检索编排：dense embedding、BM25、全局 RRF、策略后处理、可选 rerank、结构化 evidence 回传。
- Agentic KB Chat：支持 query rewrite、decomposition、variant、HyDE、多路 fanout 检索和 evidence 绑定。
- Deep Research：支持 session 化研究流程、澄清问题、研究计划、runtime workspace、最终报告与展示快照。
- 可观察与可导出：保留 `report_md`、`report_json`、`metrics_snapshot`、`gate_snapshot`、`presentation_snapshot` 等工件。

## Architecture

系统由四个主要部分组成：

- `frontend/`：Next.js 前端，负责知识库管理、KB Chat、Deep Research Workbench 与工件展示。
- `backend/`：FastAPI、Celery、文档解析、分块、Embedding、Milvus 检索、KB Chat agent、Deep Research runtime。
- `infra/`：Podman 基础设施、SearXNG 配置、本地开发依赖。
- `scripts/`：本地一键启动、快速验收、辅助脚本。

系统有两条核心业务链路：

### 1. Knowledge Base Ingestion + KB Chat

1. 上传文档或 URL。
2. backend 解析原始内容，得到 `ParsedDocument`。
3. `ChunkingEngine` 按知识库自己的 `index_config` 执行分块。
4. `ContextualEmbeddingService` 为 chunk 生成可选的补充上下文。
5. worker 生成 `embedding_text`，写入 PostgreSQL 与 Milvus。
6. KB Chat 通过 `kb_retrieve` 调 `RetrievalService`，返回带引用编号的上下文。
7. agent 或前端基于结构化 evidence 渲染回答、引用与证据面板。

### 2. Deep Research Runtime

1. 前端创建 `research session`。
2. 后端为 session 生成 `plan_snapshot`、澄清问题、workspace scaffold 与初始工件。
3. runtime 按固定阶段执行研究，从 web、paper、workspace 等来源补证。
4. runtime 将 claim、evidence、section brief、report draft、live board 等内容写回 workspace。
5. finalizer 产出 `report_md`、`report_json`、`metrics_snapshot`、`gate_snapshot`。
6. `presentation_snapshot` 将这些工件压成前端友好的展示模型。

## Quick Start

### 环境要求

- Windows 11
- Python 3.13+
- Node.js `^20.19.0 || >=22.12.0`
- `uv`
- Podman（建议 Podman Desktop；`podman-compose` 仅作为回退方式）

### 1. 准备配置

1. 复制 `.env.example` 为 `.env`，至少补齐：
   - `NEXT_PUBLIC_API_BASE_URL`
   - `BACKEND_PUBLIC_BASE_URL`
   - `FRONTEND_PUBLIC_BASE_URL`
   - `CORE__DATABASE_URL`
   - `STORAGE__MINIO_*`
   - `CORE__EMBEDDING_*`
   - `WEB_SEARCH__SEARXNG_DEFAULT_ENGINES`
2. 如需覆盖基础设施变量，复制 `infra/env/dev.env.example` 为 `infra/env/dev.env` 后修改。
3. 若 backend/frontend/worker 运行在宿主机，请把数据库、Redis、MinIO、Milvus、SearXNG 地址改成宿主机可达地址。

说明：

- `WEB_SEARCH__SEARXNG_DEFAULT_ENGINES` 默认收敛到已验证可用的 `artic / arxiv / github / mdn / openairepublications / stackoverflow`。
- 若修改 SearXNG engine 列表，需要同步更新 `infra/searxng/config/settings.yml`。
- 单一 compose 与旧绑定目录之间不会自动迁移历史数据，需要手动备份或导入。

### 2. 一键启动

以下脚本面向 Windows 本地开发，不作为生产部署入口：

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

常用参数：

- `-SkipInfra`
- `-NoDetachInfra`
- `-SkipBackend`
- `-SkipWorker`
- `-SkipFrontend`
- `-RunMigrate`
- `-Verbose`

补充说明：

- 默认跳过数据库迁移；首次建库或重置后请显式添加 `-RunMigrate`。
- `scripts/start_all.ps1` 会在执行 `uv` 前清理外部 `VIRTUAL_ENV / CONDA_PREFIX / PYTHONHOME / PYTHONPATH`，并固定使用 `backend/.venv`。
- 若数据库来自旧迁移链，请先清理旧 schema，再执行 `uv run alembic upgrade head`。

### 3. 本地验收

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1 -SkipInfra
pwsh -ExecutionPolicy Bypass -File .\scripts\verify_quickstart.ps1
```

### 4. 手动启动（仅排障）

基础依赖：

```powershell
pwsh -ExecutionPolicy Bypass -File .\infra\up.ps1
```

后端：

```powershell
Set-Location .\backend
uv sync
uv run uvicorn app.main:app --host $env:BACKEND_BIND_HOST --port $env:BACKEND_PORT --loop app.core.uvicorn_loop:windows_selector_loop_factory
```

Worker + Beat：

```powershell
Set-Location .\backend
uv run celery -A app.worker.celery_app beat
uv run celery -A app.worker.celery_app worker -n worker.dispatch@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q dispatch
uv run celery -A app.worker.celery_app worker -n worker.core@%h --pool=threads --concurrency=8 --prefetch-multiplier=1 -Q ingestion,rebuild,default
uv run celery -A app.worker.celery_app worker -n worker.noncore@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q research,export
```

前端：

```powershell
Set-Location .\frontend
npm install
npm run build
npm run start -- --port $env:FRONTEND_PORT
```

## Research API

Deep Research 对外主契约以 session 为中心：

- 统一主标识：`session_id`
- 统一入口前缀：`/api/v1/research/sessions*`
- 创建会话：`POST /api/v1/research/sessions`
- 提交澄清：`POST /api/v1/research/sessions/{session_id}/clarification`
- 更新研究计划：`POST /api/v1/research/sessions/{session_id}/plan`
- 启动执行：`POST /api/v1/research/sessions/{session_id}/start`
- SSE 订阅：`GET /api/v1/research/sessions/{session_id}/stream`
- 停止任务：`POST /api/v1/research/sessions/{session_id}/stop`
- 读取工件：`GET /api/v1/research/sessions/{session_id}/artifacts`

工件读取接口返回 `research_artifacts` 列表，后端会在原始工件之外额外拼出一个 `presentation_snapshot` 供前端直接消费。

## 模型配置

- 运行时主模型配置通过前端「模型配置」页面维护：provider、Base URL、API Key、模型列表、全局生效模型。
- `.env` 主要承载部署配置、Embedding、Web 搜索与公开地址，不作为运行时 LLM 主配置表。
- `llama.cpp` provider 支持填写 `http://<host>:8080`、`/v1` 或完整 `/v1/chat/completions`，保存时会规范化为 `/v1`。

## 知识库索引与导入细节

### 文档导入链路

- PDF 默认优先走 MinerU pipeline。
- 若 MinerU 失败或输出为空，会回退到 `pypdf` 文本提取。
- URL / DOCX / Markdown / TXT 继续走各自已有解析链路。
- 单文件上传上限为 `50MB`。

导入任务在 `backend/src/app/worker/tasks/ingestion_batches.py` 中执行，核心步骤是：

1. `parse_material(...)` 解析原文。
2. `ChunkingEngine.split(...)` 生成 chunk。
3. `generate_contexts_for_chunks(...)` 调 `ContextualEmbeddingService` 生成可选 `context_text`。
4. `build_embedding_inputs(...)` 组合 `embedding_text`。
5. `embed_inputs_with_concurrency(...)` 执行 embedding。
6. `ChunkPersistenceService.replace_material_chunks(...)` 覆盖式写入 PostgreSQL。
7. `_write_records_to_milvus(...)` 清理旧向量后再 upsert 到 Milvus。

这条链路是幂等覆盖式的：同一 `(kb_id, material_id)` 重跑会先删旧 chunk 再写新 chunk，不会累积重复数据。

### 每个知识库的索引配置

每个知识库都可以保存自己的 `index_config`，当前结构分两部分：

- `chunking`
- `contextual`

`contextual` 控制是否为 chunk 生成额外上下文文本：

- `enabled`：默认 `true`
- `max_tokens`：默认 `192`
- `concurrency`：默认 `2`

生成后的 chunk 会同时落多份文本字段：

- `raw_text`：原始 chunk 文本
- `embedding_text`：送去 embedding 的最终文本
- `context_text`：为检索和回答额外生成的上下文文本
- `context_status` / `context_error` / `context_attempts`：上下文生成结果与重试信息

### 分块策略

项目当前支持四种分块策略：

#### 1. `query_dependent_multiscale`

默认策略。配置为多个 token window，默认三档：

- `128 / 32`
- `256 / 64`
- `512 / 128`

含义：

- 同一文档会被切成多套不同尺度的 chunk。
- 每个 chunk 记录 `window_id`、`window_size_tokens`、`window_overlap_tokens`、`token_start`、`token_end`。
- 写入 Milvus 时，每个 window 会进入自己的 collection。
- 检索阶段可先做常规 RRF，再做 multiscale 二次融合。

适用场景：

- 用户问题粒度不稳定。
- 既要召回细粒度定义，也要召回长上下文段落。

#### 2. `max_min_semantic`

语义分块。默认参数：

- `min_tokens = 80`
- `max_tokens = 320`
- `threshold_mode = percentile`
- `breakpoint_percentile = 25`
- `similarity_threshold = 0.7`
- `overlap_chars = 96`
- `embedding_batch_size = 32`

实现方式：

- 先按句切分。
- 对句子做 embedding。
- 通过相邻句向量余弦相似度决定断点。
- 若 embedding 失败，自动回退到第一档 `query_dependent_multiscale` window。

这个回退不是静默丢失，chunk metadata 会记录：

- `semantic_fallback = true`
- `semantic_fallback_reason`
- `fallback_window_size_tokens`
- `fallback_window_overlap_tokens`

#### 3. `parent_child`

双层 chunk：

- parent 默认 `1200 / 120`
- child 默认 `240 / 40`

行为：

- parent chunk 先生成并持久化。
- child chunk 带 `parent_ref` / `child_seq`。
- 检索命中 child 后，可在检索后处理阶段回到 parent 上下文。

适合精确命中点很小，但回答需要更大原文范围的资料。

#### 4. `markdown_heading`

Markdown 专用策略，默认：

- `max_heading_level = 3`
- `chunk_size = 800`
- `chunk_overlap = 160`

行为：

- 第一阶段用 `MarkdownHeaderTextSplitter` 按标题树拆 section。
- 第二阶段只在 section 内继续细分，不跨 section 边界。
- chunk metadata 会保留 `heading_path`。

如果文档没有有效标题树，自动回退到非 Markdown 策略。

## KB 检索编排细节

### 检索入口

KB Chat 的统一工具入口是 `kb_retrieve`，实现位于：

- `backend/src/app/agents/tools/kb_retrieve.py`

它不是一个简单的“向量查 top-k”包装，而是统一承接：

- 单查询检索
- 多查询 fanout
- decomposition / variant / HyDE 融合
- evidence 草稿与 citation catalog 回传

### 检索层主流程

`RetrievalService.retrieve(...)` 的主流程是：

1. 规范化 query。
2. 按 feature flag 决定是否执行 query rewrite。
3. 读取知识库 index config，构造 KB fingerprint。
4. 结合 query、KB 内容版本、检索策略参数生成 cache key。
5. 命中缓存时直接回填 chunk，再做 parent/child 补全与 citation label 补全。
6. 未命中缓存时进入统一 `retrieve_layer(...)`。

### `retrieve_layer(...)` 的实际执行顺序

统一检索层不是单步，而是一个固定编排：

1. 读取 query items。
2. 对每个 query item 并发 fanout。
3. 每个 fanout 分支执行 hybrid 检索：
   - dense embedding
   - sparse BM25
   - Milvus `hybrid_search`
4. 分支级结果先去重。
5. 所有分支通过全局 RRF 融合。
6. 回填 PostgreSQL chunk 详情。
7. 进行 section 邻居扩展。
8. 应用 `parent_child` 检索后处理。
9. 应用 `query_dependent_multiscale` 检索后处理。
10. 补充 citation label。
11. 进行 score cutoff。
12. 精确去重、内容 hash 去重、语义相似度去重。
13. 可选 rerank。
14. 生成最终 `evidence_items`、`retrieval_candidates`、`reranked_candidates`。

可以把它理解为：

`hybrid_search -> global RRF -> strategy expansion -> dedupe -> optional rerank -> Top-N`

### Query rewrite 与多查询策略

查询增强服务 `QueryRewriteService` 同时给普通 retrieval 与 KB Chat agentic preprocess 复用。当前支持：

- `rewrite`：普通检索 query rewrite
- `resolve_reference` / `coref_rewrite`：结合 recent turns、summary、memory 解析指代
- `normalize_rewrite`：标准化 rewrite
- `classify_complexity`：判断走 direct / multi_query / decomposition
- `decompose`：把复杂问题拆成 sub query
- `generate_variants`：多路变体检索
- `hyde`：生成 HyDE query
- `plan_retrieval_budget`：按复杂度与失败原因给出本轮检索 budget

KB Chat agentic 检索并不是固定单 query。它会把多种查询形态统一规范成 `query_items`，再交给 `kb_retrieve` 走融合检索：

- main query
- subquery
- paraphrase
- variant
- hyde

### KB Chat 的 fanout 检索

`backend/src/app/agents/kb_chat_agentic/reflection_retrieval.py` 里，agent 会先决定：

- 是否维持 `single_retrieve`
- 是否进入 `parallel_fanout`

fanout 时会：

1. 根据策略筛选可用 `query_items`。
2. 计算质量分，优先高质量 query。
3. 控制最小分支数与最大并行分支数。
4. 为每个分支调用 `kb_retrieve`。
5. 将各分支结果合并成最终 `final_context`。
6. 生成 `retrieval_diagnostics`、`metrics.retrieval_layer`、`citation_catalog`。

所以 KB Chat 的“检索编排”不是前端拼提示词，而是 backend agent graph 自己决定：

- 什么时候拆
- 拆几路
- 每路 budget 多大
- 怎么融合
- evidence 怎么绑定回最终回答

### 检索结果里保存了什么

检索层除了返回文本，还会产出结构化信息：

- `evidence_items`
- `citation_catalog`
- `kb_scope`
- `retrieval_round`
- `usage`
- `truncation`
- `retrieval_candidates`
- `reranked_candidates`

回答文本中的引用编号如 `S1 / S2`，与这些结构化 evidence 是同一批结果，不是后处理硬拼。

## 上下文管理细节

### 知识库问答的上下文

KB Chat 的上下文不是简单把 `chunk.content` 直接喂给模型，而是尽量使用：

- `context_text`，如果它存在
- 否则退回 `chunk.content`

`context_text` 的来源是 `ContextualEmbeddingService`。它会：

1. 从全文里截取 chunk 周边最多约 2000 字符的源文本。
2. 调提示词 `ingestion/contextual_embedding` 生成一段短上下文。
3. 作为检索和回答阶段更稳定的 `context_text`。

这样做的目的不是“摘要原文”，而是给 chunk 补齐局部语义、章节意图或上下文框架，减少只看单个短片段时的歧义。

### Deep Research 的上下文组织

Deep Research 不走“把全部历史消息塞给模型”的做法，而是走文件化上下文。

运行时会为每个 `session_id` 构建一套 workspace：

- workspace 根：`/workspace/research/<session_id>`
- scratch 根：`/scratch/research/<session_id>`
- 上下文引导目录：`/workspace/context`

其中有三层最关键的上下文机制：

#### 1. Context guide

`build_runtime_context_guide(...)` 会生成 `runtime_context_guide.md`，明确告诉 runtime：

- 优先读哪些文件
- 哪些文件是 handoff surface
- 哪些只是 projection
- 哪些属于 on-demand spill / scratch

priority read order 以这些文件为主：

- `/workspace/context/runtime_context_guide.md`
- `/workspace/context/session_question.txt`
- `/workspace/context/plan_snapshot.json`
- `/workspace/context/query_mesh.json`
- `/workspace/context/clarification_context.md`
- `mission / plan / claim_map / evidence_ledger / claim_bundles / section_briefs / report_context / task_graph`

#### 2. 文件预算与 spill

`build_runtime_request_files(...)` 会按 token budget 组装发给 runtime 的文件集合。

核心规则：

- priority 文件优先进入请求
- 非 priority 文件只有在预算允许时才会被内联
- 超预算文件会进入 `spilled_paths`
- 某些超长 bootstrap artifact 会被写成 spill 文件，只在原路径留摘要和跳转信息

这保证了：

- runtime 首轮上下文可控
- 大结果不会把窗口挤爆
- 需要时还能按路径继续下钻

#### 3. 低频记忆文件

runtime 还会注入一个运行时 memory 文件：

- `/memories/deep-research/runtime-memory.md`

它只保存低变更、已验证的运行规则，比如：

- 哪些 JSON 是 handoff 面
- `live-board.json` 只是投影，不是唯一真相源
- 不要把原始搜索结果或瞬时 tool dump 写进 memory

### 澄清上下文

如果研究任务先经历了 clarifying 阶段，runtime 还会额外注入：

- 原始问题
- 已发出的澄清问题
- 已收到的澄清回答

这个上下文文件是 `clarification_context.md`，用来避免 planner 与 runtime 对研究边界理解不一致。

## Deep Research 细节

### 运行时入口

Deep Research 的主入口是：

- `build_deep_research_runtime_runner(...)`
- `DeepResearchRuntimeRunner.run_session(...)`

执行前会初始化：

- LangGraph Postgres pool
- CheckpointManager
- StoreManager
- 主模型 / 子代理模型 / finalizer 模型
- runtime system prompt
- run-scoped skills

### Runtime 禁止项

Deep Research runtime 有明确硬约束：

- 禁止启用 MCP 工具
- 禁止使用 LocalShellBackend
- 不允许依赖 DeepAgents 内部 graph API

这意味着它是一个受限、可控的研究运行时，不是开放式全能 agent。

### Workspace scaffold

每个 session 开始运行前，后端会创建一组固定工件路径：

- `00-mission.md`
- `01-plan.md`
- `02-report-draft.md`
- `03-report-outline.md`
- `04-claim-map.json`
- `05-evidence-ledger.json`
- `06-task-graph.json`
- `07-claim-bundles.json`
- `08-section-briefs.json`
- `09-live-board.json`
- `report/report-context.json`
- `critique/evidence-critique.json`
- `critique/coverage-critique.json`

这些路径不是装饰，它们是 runtime 协作协议的一部分。

### Deep Research 强制阶段顺序

runtime skill 已固定研究阶段顺序：

1. `breadth-pass`
2. `breadth gate`
3. `outline / section-briefs`
4. `depth-pass`
5. `draft-pass`
6. `critic-pass`
7. `finalize-pass`

额外硬约束：

- critic-pass 必须调用 `evidence-critic` 和 `coverage-critic`
- 最多回流 2 次
- structured response 必须满足最终契约

### 研究过程中的核心 JSON

如果只看最关键的中间状态，重点是：

- `04-claim-map.json`
- `05-evidence-ledger.json`
- `06-task-graph.json`
- `07-claim-bundles.json`
- `08-section-briefs.json`
- `report-context.json`

角色分工大致如下：

- `claim-map`：记录当前主张与支持/反对状态
- `evidence-ledger`：记录证据账本
- `task-graph`：记录 claim/source/section/report 任务图
- `claim-bundles`：把 claim 与 section、证据、限制项绑定起来
- `section-briefs`：为章节扩写准备结构化 brief
- `report-context`：维护执行摘要、关键要点、建议、开放问题、章节状态、置信度等

`live-board.json` 仅用于运行态观测，不是 planning source of truth。

### Deep Research 最终工件

最终阶段会落盘或持久化的关键工件包括：

- `report_md`
- `report_json`
- `claim_map_json`
- `coverage_matrix_json`
- `conflicts_json`
- `source_ledger_json`
- `metrics_snapshot`
- `gate_snapshot`
- `quality_snapshot`（若质量快照存在）
- `presentation_snapshot`

其中：

- `report_md`：最终 Markdown 报告正文
- `report_json`：结构化报告
- `metrics_snapshot`：运行指标快照
- `gate_snapshot`：gate 结果快照
- `presentation_snapshot`：前端展示模型

前端研究页优先消费 `presentation_snapshot`，而不是自己重组全部原始工件。

### Source quality 与 citation 收口

runtime 不会把所有 citation 原样放进最终报告。`DeepResearchRuntimeRunner` 会：

1. 恢复或合成 `structured_response`
2. 用严格 schema 校验
3. 经过 `ResearchSourceQualityJudge` 过滤 citation
4. 再构建 `ResearchSourceBundle`
5. 最后交给 finalizer 输出报告

因此最终引用不是“搜到就算”，而是经过：

- 结构化恢复
- 契约校验
- 质量过滤
- bundle 汇总

这几层收口。

## Web 搜索与外部资料

### Web 搜索

- 必填：`WEB_SEARCH_API_KEY`
- 可选搜索源：`SEARXNG_SEARCH_ENABLED`、`WEB_SEARCH__SEARXNG_SEARCH_BASE_URL`
- 可选正文增强：`JINA_READ_ENABLED`、`JINA_READ_BASE_URL`

普通聊天网页搜索在 `backend/src/app/search/web/pipeline.py` 中有独立 pipeline，支持：

- 搜索 query plan
- 文档融合
- 可选 enrichment
- rerank

Deep Research 会根据 `plan_snapshot.target_sources` 与复杂度选择需要的 web provider。

## 已知边界

### KB Chat

- 仅支持内部工具，如 `kb_retrieve`
- 不加载 MCP 外接工具
- 不支持两阶段工具审批
- 不依赖 Human-in-the-loop

### Deep Research

- 当前实现是受限研究运行时，不是开放式通用 agent sandbox
- 强依赖 session 工件、workspace 协议与 structured output 契约
- 前端展示围绕 `presentation_snapshot` 和 research artifacts 工作

## 生产配置与 Secrets

生产部署请使用：

- `infra/podman-compose.yml`
- `infra/env/prod.env.example`

关键原则：

- feature flags 不是 secrets manager
- `NEXT_PUBLIC_*` 只承载浏览器可见配置，不承载 secrets
- 默认口令、宿主机代理 IP、loopback URL 不进入共享模板

## 代码入口导航

如果要继续读实现，优先从这些文件开始：

- 知识库 schema 与索引配置：`backend/src/app/schemas/knowledge_bases.py`
- 分块引擎：`backend/src/app/services/chunking.py`
- 上下文增强：`backend/src/app/services/contextual_embedding_service.py`
- 导入任务：`backend/src/app/worker/tasks/ingestion_batches.py`
- KB 检索工具：`backend/src/app/agents/tools/kb_retrieve.py`
- 检索层主流程：`backend/src/app/services/retrieval_service_retrieve_ops.py`
- 统一 RetrievalLayer：`backend/src/app/services/retrieval_service_layer_ops.py`
- 查询增强：`backend/src/app/services/query_rewrite_service.py`
- KB Chat agentic 检索编排：`backend/src/app/agents/kb_chat_agentic/reflection_retrieval.py`
- Deep Research runtime 入口：`backend/src/app/services/deep_research_runtime.py`
- runtime 上下文管理：`backend/src/app/services/research_runtime_context.py`
- runtime 文件预算与 prompt：`backend/src/app/services/research_runtime_workspace.py`
- runtime scaffold 路径：`backend/src/app/services/research_workspace_files.py`
- research artifacts / presentation snapshot：`backend/src/app/services/research_service_contracts.py`
