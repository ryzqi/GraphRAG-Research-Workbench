# Deep Research API Contract

本文档描述当前 Phase 1 已落地的 Deep Research 后端契约，范围只覆盖仓库内已经实现并由服务层实际写出的 artifact 与 `report_json` / citation 结构。

## research_artifacts

当前后端会持久化的核心 artifact 如下：

| artifact_key | 类型 | 说明 |
| --- | --- | --- |
| `report_json` | JSON object | 最终研究报告的结构化结果 |
| `report_md` | Markdown | 最终研究报告的人类可读版本 |
| `claim_map_json` | JSON array | 最终 `report_json.claim_map` 的投影 |
| `coverage_matrix_json` | JSON object | 最终 `report_json.coverage_matrix` 的投影 |
| `conflicts_json` | JSON array | 最终 `report_json.conflicts` 的投影 |
| `source_ledger_json` | JSON array | 最终 `report_json.source_ledger` 的投影 |
| `runtime_claim_map_json` | JSON object | 运行时事实源 `claim-map.json` 的快照 |
| `runtime_evidence_ledger_json` | JSON object | 运行时事实源 `evidence-ledger.json` 的快照 |
| `runtime_evidence_critique_json` | JSON object | `evidence-critic` 输出的事实源快照 |
| `runtime_coverage_critique_json` | JSON object | `coverage-critic` 输出的事实源快照 |
| `runtime_files_budget_snapshot` | JSON object | 本轮 request files 预算快照 |
| `metrics_snapshot` | JSON object | 研究会话 metrics 总快照 |
| `gate_snapshot` | JSON object | gate 评估结果快照 |
| `quality_snapshot` | JSON object | Phase 1 新增的质量指标快照 |

不再承诺为后端契约的旧 projection / markdown artifact：

- `claim_map_md`
- `evidence_ledger_md`
- `analysis_notes_md`
- `coverage_md`
- `query_map_md`

这些 markdown 文件已不再作为运行时事实源；其中 `claim_map_md` 若继续存在，也只应视为面向展示层的投影，而不是 API 契约的一部分。

## report_json 结构

`report_json` 由 `research_finalizer` 收口，当前包含这些顶层字段：

- `question`
- `target_sources`
- `summary`
- `findings`
- `coverage_gaps`
- `provider_counts`
- `citations`
- `sections`
- `metadata`
- `claim_map`
- `coverage_matrix`
- `conflicts`
- `source_ledger`

### report_json.claim_map

`claim_map` 为数组，每项字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `claim_id` | string | claim 标识 |
| `claim` | string | 原始 claim 文本 |
| `verdict` | `supported \| contested \| insufficient` | alignment judge 裁决结果 |
| `supporting_evidence_ids` | string[] | 支撑证据 ID 列表 |
| `conflicting_evidence_ids` | string[] | 冲突证据 ID 列表 |
| `missing_aspects` | string[] | 尚未闭合的证据缺口 |
| `reason` | string | 裁决理由摘要 |

### report_json.coverage_matrix

`coverage_matrix` 当前字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `provider_counts` | object | provider -> citation 数量 |
| `missing_providers` | string[] | 仍未覆盖的 provider / 来源缺口 |
| `alignment_pass_rate` | number | `supported` claim 占比 |
| `missing_aspects_total` | number | 所有 claim 的 `missing_aspects` 总数 |

### report_json.source_ledger

`source_ledger` 为数组，每项字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `provider` | string | citation 的 `source_provider` |
| `origin_url` | string \| null | 原始来源 URL |
| `title` | string \| null | 标题 |
| `source_type` | string | `web` / `paper` |
| `excerpt_count` | number | citation 附带 excerpt 数量 |

## citation 结构

Deep Research 最终 citation 使用 `ResearchCanonicalCitation`，当前字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_type` | string | 来源类型 |
| `source_provider` | string | 标准 provider id，例如 `workspace` / `tavily` / `searxng` / `jina_reader` / `arxiv` |
| `retrieval_method` | string | 采集方式，例如 `web_search` / `read_file` |
| `source_id` | string | 来源唯一标识 |
| `title` | string \| null | 标题 |
| `url` | string \| null | 当前引用 URL |
| `origin_url` | string \| null | 原始来源 URL；网页来源必填 |
| `arxiv_id` | string \| null | arXiv ID |
| `authors` | string[] | 作者列表 |
| `published_at` | datetime \| null | 发布时间 |
| `pdf_url` | string \| null | PDF 地址 |
| `accessed_at` | datetime \| null | 访问时间 |
| `retrieved_at` | datetime | 本次抓取时间 |
| `excerpts` | object[] | 原文摘录列表，长度 1 到 5 |
| `provider_snippet_hash` | string \| null | provider 侧摘要哈希 |

### citation.excerpts[]

每个 excerpt 字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `text` | string | 40 到 400 字的原文摘录 |
| `locator` | string \| null | 定位信息，例如段落、标题或页码 |
| `lang` | `zh \| en \| mixed` | 摘录语言 |
