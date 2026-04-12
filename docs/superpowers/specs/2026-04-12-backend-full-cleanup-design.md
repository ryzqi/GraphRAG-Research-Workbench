# Backend 全量安全清理设计

## 背景

用户要求对 `F:\毕设\code\backend` 做逐文件、全量、以安全为前提的代码清理，并要求：

- 先创建 `md` 文件记录 `backend` 下所有代码文件名
- 每分析并清理完一个文件就在前面打勾
- 每完成一个里程碑就创建 git 提交
- 启用子代理做分析
- 子代理模型限制为 `gpt-5.4` + `high reasoning`

## 目标

在不误删仍有运行价值代码的前提下，清理后端中以下类型的问题：

- 冗余实现
- 遗留桥接/兼容分支
- 无用 helper / contract / serializer / adapter
- 已被拆分模块吸收但原文件中仍残留的死路径
- 过期测试或仅服务于已移除行为的测试残骸

## 非目标

- 不做无关重构
- 不为了“看起来更整洁”而改写仍有价值的稳定实现
- 不在证据不足时删除 Alembic 迁移链
- 不基于主观风格调整提示词内容
- 不触碰 `backend/.venv`、缓存、构建产物等非一方代码

## 唯一事实源

本次“后端代码文件列表”以 `git ls-files backend` 结果为准，再过滤掉显然不是仓库一方源码的目录。该事实源决定：

1. 清单中的文件范围
2. 子域拆分
3. 每个文件的审查完成标记

## 安全清理准则

只有同时满足下列条件，才允许删除或收缩实现：

1. 已核查静态引用
2. 已核查动态入口：
   - FastAPI router 注册
   - Celery task include
   - 生命周期初始化
   - 提示词模板加载
   - 模型 provider / adapter 注册
   - 运行时字符串导入或配置驱动加载
3. 已有或已补充行为验证，能证明“保留功能仍工作”
4. 修改后执行了与结论直接对应的 fresh verification

## 里程碑设计

### Milestone 0: 基线落盘

- 创建计划文件、设计文档、实施计划、逐文件清单
- 切出专用分支
- 产出子域拆分和审查顺序

### Milestone 1: 入口与基础层

- `api`、`bootstrap`、`core`、`db`、`integrations`、`worker`
- 目标是先清理系统入口周边的明显遗留代码，同时确认动态注册边界

### Milestone 2: agent/tool/search/prompt 层

- `agents`、`search`、`prompts`
- 目标是找出拆分后的残余 helper、重复 contract、废弃工具路径

### Milestone 3: service 层非 research

- general chat / ingestion / retrieval / export / parsing / semantic cache
- 目标是清理 service 拆分后仍残留的桥接和重复逻辑

### Milestone 4: research 运行时

- `deep_research_runtime.py`、`research_service*.py`、`research_runtime_*.py`、`research_*`
- 目标是保证单一事实源和运行时契约前提下的安全清理

### Milestone 5: 回归与收尾

- 聚合所有改动
- 做复审和最终验证

## 子代理策略

- 控制器负责：
  - 唯一事实源维护
  - 清单更新
  - 里程碑切分
  - 最终改动整合与验证
- 子代理负责：
  - 逐子域静态审查
  - 候选清理项论证
  - 在明确边界内实施局部清理
- 模型约束：
  - 所有子代理统一使用 `gpt-5.4`
  - `reasoning_effort=high`

## 验证策略

- 优先使用与改动直连的现有后端测试
- 必要时补充最小化回归测试，遵守先红后绿
- 对“删代码”场景，验证目标不是“删掉了”，而是“保留行为仍正确”
- 若测试受环境限制阻塞，明确标记 `受限未执行`，并补等价验证

## 交付物

- `task_plan.md`
- `findings.md`
- `progress.md`
- 本设计文档
- 实施计划文档
- `backend` 逐文件清理清单
- 分里程碑 git 提交
