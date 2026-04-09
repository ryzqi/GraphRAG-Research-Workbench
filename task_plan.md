# 深度研究运行时优化总计划

## 目标

按用户指定顺序完成 3 个连续任务，并在每个任务结束后完成 fresh verification 与 Git 提交：

1. 调研并优化当前项目的上下文管理。
2. 调研并优化当前项目对 DeepAgents 特性的使用。
3. 调研并优化当前项目的深度研究提示词与模板。

任务全部完成后，启动子代理做最终审查，并根据审查结果继续补改直到收敛。

## 约束

- 保持连续执行，中间不做常规等待。
- 高风险破坏性操作除外；当前未发现必须暂停的操作。
- 只做与本次目标直接相关的最小改动。
- 不回滚现有未提交改动，先将其视为当前基线的一部分。
- 每个任务都遵守先调研、再设计、再测试、再实现、再验证、再提交。

## 当前事实

- 仓库当前存在未提交改动，集中在 `backend/src/app/services/deep_research_runtime.py`、`backend/src/app/prompts/templates/research/*`、`backend/src/app/services/research_*` 与对应测试文件。
- `Agent Reach doctor` 已确认当前 7/7 渠道可用。
- 当前研究运行时主链路位于 `backend/src/app/services/research_service.py` -> `backend/src/app/services/deep_research_runtime.py`。

## 阶段

| 阶段 | 状态 | 完成判据 |
| --- | --- | --- |
| Phase 0: 基线与规划 | completed | planning/spec/plan 文档落盘，仓库与搜索能力已验证 |
| Phase 1: 上下文管理优化 | completed | 外部最佳实践完成、失败测试 -> 通过、代码提交 |
| Phase 2: DeepAgents 优化 | completed | 外部最佳实践完成、失败测试 -> 通过、代码提交 |
| Phase 3: Prompt/模板优化 | completed | 外部最佳实践完成、失败测试 -> 通过、代码提交 |
| Phase 4: 最终审查与收尾 | pending | 子代理审查完成，遗留问题处理完毕，给出最终状态 |

## 风险与边界

- 若现有未提交改动与本次任务目标直接冲突，需要先读清差异再决定是否在其上继续增量修改。
- 若某阶段验证依赖外部服务不可用，则如实标注 `受限未执行`，但会先完成本地可验证部分。

## 错误记录

暂无。
