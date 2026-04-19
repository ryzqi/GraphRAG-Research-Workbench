# Deep Research Architecture

本文档仅描述当前仓库里已经落地的 Deep Research Phase 1 结构，不覆盖 Phase 2 / Approach C 的未来方案。

## Deep Research Pipeline

当前主代理与运行时提示词、技能文件、breadth gate 代码保持同一顺序：

```text
breadth-pass
  -> breadth gate
  -> outline + section-briefs
  -> depth-pass
  -> draft-pass
  -> critic-pass
  -> finalize-pass
```

阶段含义：

- `breadth-pass`：按 `plan.subtasks` 委派 `claim-verifier`，先让每条 pending claim 至少拿到 1 条 evidence。
- `breadth gate`：由代码检查 claim-map / evidence-ledger 的 breadth 条件，只在达到最小证据门槛后放行后续委派。
- `outline + section-briefs`：大纲与 section brief 只能建立在已收集证据之上，不再走旧的 outline-first gate。
- `depth-pass`：围绕 claim 继续委派 `web-researcher` / `paper-researcher`，把支撑提升到至少 2 个独立 provider。
- `draft-pass`：由 `section-writer` 基于 claim bundle 扩写正文。
- `critic-pass`：并行运行 `evidence-critic` 与 `coverage-critic`，它们输出的 JSON 进入运行时事实源。
- `finalize-pass`：由 `citation-steward` 做 citation / excerpt 审计，随后 finalizer 输出 `report_md` 与 `report_json`。

## Runtime Artifacts

当前 Deep Research 把这些 JSON 文件视为事实源：

- `claim-map.json`
- `evidence-ledger.json`
- `claim-bundles.json`
- `section-briefs.json`
- `report-context.json`
- `evidence-critique.json`
- `coverage-critique.json`

人类可读的 markdown 文件例如 `report-outline`、`report-draft`、`claim-map.md`、`evidence-ledger.md` 只作为投影，不再作为运行时事实源。

## Subagents

当前 Deep Research 子代理集合已经从旧的 5 个扩展到 7 个：

| 子代理 | 主要职责 |
| --- | --- |
| `web-researcher` | 使用网页搜索与页面读取工具补充 web 证据 |
| `paper-researcher` | 使用 arXiv 工具补充论文证据 |
| `claim-verifier` | 围绕单个 claim 组织证据、反证与状态裁决 |
| `section-writer` | 基于已验证工件写章节，不直接搜索 |
| `citation-steward` | finalize 前审计 citation 与 excerpts |
| `evidence-critic` | 只读检查 claim 与 evidence 的对齐，产出 `evidence-critique.json` |
| `coverage-critic` | 只读检查 provider 多样性、反证覆盖与 orphan citation，产出 `coverage-critique.json` |

## Alignment And Verification

Phase 1 已新增 alignment judge 链路：

- `ResearchAlignmentJudge` 负责 claim 与 evidence 的语义对齐裁决。
- `ResearchFinalizer` 在 `finalize_async(...)` 中调用异步 verification helper，生成：
  - `claim_map`
  - `coverage_matrix`
  - `conflicts`
  - `source_ledger`
- `coverage_matrix` 当前额外包含：
  - `alignment_pass_rate`
  - `missing_aspects_total`

这意味着 finalizer 不再依赖旧的 token-match verification，而是依赖 claim / evidence / citation 的结构化对齐结果。

## Observability

当前 Deep Research 的可观测性除 `metrics_snapshot` 与 `gate_snapshot` 外，还新增了 `quality_snapshot`。它当前包含 5 个指标：

- `claim_alignment_rate`
- `citation_excerpt_presence`
- `independence_source_ratio`
- `counter_evidence_exposure`
- `citation_orphan_rate`

此外，运行时还会持久化 `runtime_files_budget_snapshot`，用于记录 request files 预算裁剪结果。

## Phase 2 Status

Phase 2（Approach C）在当前仓库中尚未落地。当前代码库已能找到的实现边界仍然止于：

- breadth-first Deep Research pipeline
- breadth gate / critic-pass / alignment judge
- quality_snapshot 与 runtime files budget 监控

当前仓库内未见 Phase 2 / Approach C 专属的 runtime 分支、artifact 契约、测试入口或文档锚点，因此相关内容不应在现状文档中表述为“已实现”。
