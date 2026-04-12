# Backend 全量安全清理计划

## 目标

- 对 `F:\毕设\code\backend` 的一方代码做逐文件审查，识别并清理冗余、遗留、无用代码。
- 保持“安全清理”优先：不删除仍被运行时、配置、字符串导入、路由注册、Celery 注册、提示词加载、迁移链路或测试基线需要的内容。
- 建立可持续跟踪的 `md` 清单，确保每个文件都有审查状态。

## 唯一事实源

- 本次范围以 `git ls-files backend` 返回的、且属于仓库一方代码的文件为准。
- 明确排除：`backend/.venv`、缓存目录、构建产物、第三方依赖、临时文件。

## 假设

- “backend 下所有代码文件”包含：`backend/src`、`backend/tests`、`backend/alembic`、`backend/pyproject.toml`、`backend/alembic.ini`。
- 里程碑按“子域”而不是“单文件”提交；单个文件审查完成后更新清单，单个里程碑完成后创建 git 提交。
- 当前在 `master`，执行前先切出专用清理分支，避免直接在主分支上做大规模清理。

## 阶段

### Phase 1: 基线与清单
- 状态: completed
- 动作:
  - 创建 `task_plan.md`、`findings.md`、`progress.md`
  - 创建设计文档、实施计划、逐文件清单
  - 切出工作分支
- 完成判据:
  - 清单文件已包含全部后端代码文件
  - 设计与计划已落盘
  - 已确定后续里程碑拆分

### Phase 2: 结构风险审查
- 状态: completed
- 动作:
  - 审查路由注册、Celery `include`、启动生命周期、提示词加载、模型/工具注册、字符串导入点
  - 标记“不可轻删”和“候选清理”区域
  - 启动子代理并行分析各子域
- 完成判据:
  - 每个子域都有风险说明和候选清理项
  - 无依据的“死代码”推断被排除

### Phase 3: 入口与基础层清理
- 状态: completed
- 范围:
  - `bootstrap`、`core`、`db`、`api`、`integrations`、`worker`
- 完成判据:
  - 每个变更都有对应验证
  - 相关清单项已勾选
  - 创建里程碑提交

### Phase 4: agent/tool/search/prompt 层清理
- 状态: completed
- 范围:
  - `agents`、`tools`、`search`、`prompts`
- 完成判据:
  - 静态/配置驱动引用均已核查
  - 对行为边界的测试或等价验证通过
  - 创建里程碑提交

### Phase 5: service 层非 research 清理
- 状态: completed
- 范围:
  - general chat / ingestion / retrieval / export / parsing / semantic cache 等 service
- 完成判据:
  - helper/contract/ops 拆分边界核查完成
  - 冗余实现与遗留桥接被安全移除
  - 创建里程碑提交

### Phase 6: research 运行时与报告链路清理
- 状态: completed
- 范围:
  - `deep_research_runtime.py`、`research_service*.py`、`research_runtime_*.py`、`research_*` 相关实现
- 完成判据:
  - 单一事实源不被破坏
  - 运行时/报告/产物契约验证通过
  - 创建里程碑提交

### Phase 7: 全量回归、复审、收尾
- 状态: in_progress
- 动作:
  - 汇总所有提交
  - 运行针对性测试与必要的类型检查
  - 做代码审查
  - 准备分支收尾选项
- 完成判据:
  - 所有改动均有 fresh verification
  - 无悬而未决的重要审查问题

## 里程碑提交策略

1. 规划与清单基线
2. 全量安全代码清理
3. 最终验证与收尾

## 错误与修正记录

| 问题 | 现象 | 修正 |
| --- | --- | --- |
| 初始文件枚举污染 | `Get-ChildItem -Recurse` 把 `backend/.venv` 和缓存目录纳入范围，并触发 `.pytest_cache` 权限报错 | 改用 `git ls-files backend` 作为唯一事实源，彻底排除第三方与生成物 |
| `docs/` 被忽略 | 设计文档、实施计划、清单位于 `docs/` 下，但仓库 `.gitignore` 忽略整个 `docs/` | 基线和后续里程碑提交时对这些文档使用 `git add -f`，确保审计轨迹可提交 |
| `uv` 缓存权限 | 在沙箱内执行 `uv run pytest` / `uv lock` 命中 `D:\uv\uv_cache` 权限拒绝 | 测试改走 `backend/.venv/Scripts/*` 本地可执行文件；`uv lock` 在提权后重跑 |

## 当前结论

- 已完成 378 个 backend 一方代码文件的逐文件分析，清单已全部勾选。
- 已清理所有当前能用“静态引用 + 动态边界 + 直接验证”证明安全的候选项。
- 对以下候选明确选择“暂不清理”：
  - `report_json` 的 verification 镜像 artifacts
  - `search/web/retrievers` 的零逻辑薄包装类
  - `KbChatAgenticGraph.__init__` 的兼容参数
  - 若干 research 扩展槽位 / 弱测试 / 导出面字段
- 原因：这些项要么仍处在当前契约面，要么删除收益小于误删风险，不符合“不得清理有用代码”的边界。
