# Research Rollback Drill Record

- 时间: 2026-03-30 01:35:58 +08:00
- 模式: dry-run
- 当前提交: a262b17005d07568206c3cc74471574ce9f81afa (a262b17)
- 目标回滚提交: 未指定（需人工填入最近一次 research 发布基线 commit）

## Drill Scope

- 目标链路: `create session -> confirm -> runtime -> interrupt -> resume -> final`
- 重点对象: `research_sessions` / `research_events` / `research_artifacts`、Celery `research,export` 队列、frontend research workbench
- 当前门禁:
  - `RESEARCH_GATE_MIN_QUALITY_SCORE=0.75`
  - `RESEARCH_GATE_MAX_P95_MS=120000`
  - `RESEARCH_GATE_MAX_SESSION_COST_USD=2.0`

## Preconditions

- 已确认 `scripts/start_all.ps1`、`backend`、`frontend`、`full-refactor-deep-research` 存在
- 已确认本次演练不执行破坏性 checkout / reset；如需真实回滚，必须人工审批

## Planned Rollback Steps

1. 冻结新的 research 会话入口，避免新增 session 进入 `research` / `export` 队列。
2. 记录当前提交、门禁阈值、队列/服务状态，并导出最近一次 `research_rollback_drill.ps1` 记录。
3. 备份 `research_sessions` / `research_events` / `research_artifacts` 的最新快照与关键工件。
4. 如需真实回滚，切换到最近一次 research 发布基线 commit，并重新安装依赖 / 重启 backend、frontend、Celery。
5. 运行最小回归：`POST /api/v1/research/sessions`、`GET /api/v1/research/sessions/{session_id}/artifacts`、frontend typecheck / build。
6. 校验 planner、interrupt / resume、metrics / gate 工件、导出链路与启动脚本状态。
7. 若回滚验证通过，再解除冻结；若失败，保持冻结并进入人工处置。

## Execute Notes

- 本次脚本模式: dry-run
- 真实回滚需要人工审批后执行 `git checkout <previous-good-commit>` 或等价方案
- 本次脚本只生成演练记录，不修改 git 工作树，不停止服务，不删除数据

## Result

- 记录文件已生成: `F:\毕设\code\full-refactor-deep-research\research-rollback-drill-record.md`
- 结论: 已生成 dry-run 演练记录，可作为 Task 11 交付证据。
