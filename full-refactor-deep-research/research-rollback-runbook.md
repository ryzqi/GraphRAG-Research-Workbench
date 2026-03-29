# Research Rollback Runbook

## 目标

在不引入兼容层的前提下，为当前 `session_id` 单路径 research 链路提供可演练的回滚方案，确保出现 gate 失守、故障注入失败或 interrupt / resume 契约回归时，能快速回到最近一次可发布基线。

## 触发条件

- `RESEARCH_GATE_MIN_QUALITY_SCORE`、`RESEARCH_GATE_MAX_P95_MS`、`RESEARCH_GATE_MAX_SESSION_COST_USD` 任一失守。
- `test_e2e_interrupt_resume_contract.py`、故障注入、事件回放任一失败。
- frontend / backend / worker 启动后 research 主链路无法完成 `planner -> final`。

## 回滚原则

1. 先冻结 ingress，再处理代码或环境。
2. 先保留 `research_sessions` / `research_events` / `research_artifacts` 快照，再动服务。
3. 不在回滚流程中引入旧 `/api/v1/research/runs*` 或 run-centric 兼容逻辑。
4. 回滚完成后必须重跑最小研究回归与启动验证。

## 标准步骤

1. **冻结入口**
   - 暂停新的 research session 创建与 Celery `research,export` 队列消费。
   - 在运维记录中标记“research rollback in progress”。

2. **记录现场**
   - 记录当前 commit、门禁阈值、最近一次通过的 research 验证结果。
   - 执行 `scripts/research_rollback_drill.ps1` 生成本次演练/回滚记录。

3. **保护数据**
   - 导出 `research_sessions` / `research_events` / `research_artifacts` 快照。
   - 保留最近一次成功 `report_md` / `report_json` 工件样本。

4. **切换基线**
   - 人工确认最近一次可发布 commit。
   - 在审批后执行 git checkout / deploy 回滚。
   - 重启 backend、frontend、Celery。

5. **最小验证**
   - backend：research API 当前路由仍在 `/api/v1/research/sessions*`
   - frontend：`npm run typecheck` / `npm run build`
   - worker：research / export 队列恢复正常
   - contract：create session、interrupt / resume、artifacts、gate 工件读取成功

6. **解除冻结**
   - 所有最小验证通过后，再恢复 research 入口与队列消费。

## Dry-run 证据

- 演练脚本：`scripts/research_rollback_drill.ps1`
- 最新记录：`full-refactor-deep-research/research-rollback-drill-record.md`
