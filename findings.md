# Findings & Decisions

## Requirements
- 优化当前知识库创建流程
- 全方位分析并落地可执行优化，不停留在建议层
- 重点关注设计复杂度、任务队列性能与执行期开销
- 注意清理遗留无用代码，但不能误删仍有用途的路径

## Research Findings
- 前端“新建知识库”主入口实际走 `POST /api/v1/knowledge-bases/bootstrap-create`，不是普通 `POST /api/v1/knowledge-bases`。
- `KnowledgeBaseService.create()` 本体较轻，复杂度主要来自 bootstrap job、ingestion batch、outbox dispatcher、doc worker、watchdog 和前端进度观测层。
- `IngestionBatchService` 通过 `__getattr__` 动态拼接 prepare/status helper，复杂度被拆散到多个模块，运行可行但理解和调试成本较高。
- 首次 doc 调度走 outbox，但 doc 失败自动重试直接 `apply_async`，手动 retry 又回写 outbox，存在双轨调度语义。
- 单个 doc worker 每次都重新初始化 DB engine、sessionmaker、HTTP client、embedding client、Milvus client，还会刷新运行时模型配置，固定开销偏高。
- 后端 batch SSE 实际上仍是 DB 轮询；前端还叠加 bootstrap submission 轮询与 knowledge-base ingestion-state 轮询。
- Task 5 回归时发现前端 `BatchStatus` / `DocStatus` 仍停留在旧 `processing/completed` 双态模型，导致 `queued/failed/canceled/succeeded` 新语义未完整传到类型层和展示层。
- `stream_batch_updates()` 改为只比较 snapshot key 后，`_get_event_count` 已经没有任何有效调用，属于可直接删除的观测残留。
- 多尺度 Milvus 写入当前为“全量 delete + 分窗口 ensure/delete/upsert”，窗口数越多，重复成本越高。
- `DocumentChunk` 持久化是 `delete + insert` 全量替换，适合简单正确性，但不是最省成本的写法。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 把优化目标优先集中在编排层 | 该层同时影响复杂度、吞吐、可观测性 |
| 设计阶段先锁定清理强度，再动代码 | 用户明确要求清理遗留无用代码，删除边界必须先锁 |
| 默认不做无证据的大范围 parse/embedding 改写 | 当前没有压测证据证明算法层是首要瓶颈 |
| 用户已确认按方案 C 执行 | 允许对状态模型、bootstrap 编排和观测胶水做中高强度收敛 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| 需要同时满足开发编排技能和仓库最小改动原则 | 先建控制面，再做前置设计确认，避免直接改代码 |
| Task 5 定向验证中前端 typecheck 失败 | 追到 `frontend/src/services/ingestionBatches.ts` 仍是旧状态联合类型，并同步收敛展示/恢复逻辑 |

## Resources
- `F:\毕设\code\backend\src\app\api\v1\endpoints\kb_bootstrap_jobs.py`
- `F:\毕设\code\backend\src\app\services\ingestion_batch_service.py`
- `F:\毕设\code\backend\src\app\services\ingestion_batch_service_prepare.py`
- `F:\毕设\code\backend\src\app\worker\tasks\ingestion_outbox_dispatcher.py`
- `F:\毕设\code\backend\src\app\worker\tasks\ingestion_batches.py`
- `F:\毕设\code\backend\src\app\worker\task_resources.py`
- `F:\毕设\code\backend\src\app\services\ingestion_batch_service_status.py`
- `F:\毕设\code\frontend\src\views\KnowledgeBaseCreateWizardPage.tsx`
- `F:\毕设\code\frontend\src\hooks\queries\useIngestionBatches.ts`
- `F:\毕设\code\frontend\src\services\ingestionBatches.ts`
- `F:\毕设\code\frontend\src\components\ingestion\statusPresentation.ts`
- `F:\毕设\code\frontend\src\services\ingestionBatchRecovery.ts`

## Visual/Browser Findings
- 本轮无浏览器可视化发现。
