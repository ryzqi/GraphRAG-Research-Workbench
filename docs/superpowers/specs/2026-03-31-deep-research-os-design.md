# Deep Research OS 设计方案

- 日期：2026-03-31
- 状态：设计已评审通过，待进入实施规划
- 适用仓库：`F:\毕设\code`
- 决策：采用方案 C，重做为全新的 Deep Research OS，默认 hard cut 到单一路径，不保留长期双轨兼容层

## 1. 背景

当前 Deep Research 已具备以下能力：

- 可以创建研究会话、进入澄清、排队、运行、收口与导出流程
- 已接入 Deep Agents runtime
- 已接入 Tavily、Jina Reader、SearXNG、arXiv 等研究工具
- 已有基础的前端工作台、事件流与最终报告展示

当前主要问题：

1. 前端仍偏“会话页 + 静态卡片”，不是成熟研究工作台
2. 搜索虽然接入了多个 provider，但研究编排仍偏直连式，可信度不足
3. 长程研究过程尚未真正利用 Deep Agents 的文件系统上下文能力
4. 质量判断仍偏“数量驱动”，缺少 provider 覆盖、证据映射、冲突检测等可信度结构

## 2. 用户 / 利益相关方

- 主要用户：发起深度研究任务的产品/研发用户
- 次要用户：需要审阅研究过程与证据可信度的评审者
- 系统利益相关方：前端工作台、研究运行时、后端可观测性与导出链路维护者

## 3. 用户问题 / 目标结果

### 3.1 用户问题

用户不只是要“更多搜索结果”，而是要：

- 在开始研究前看到清晰计划
- 在研究进行中理解当前阶段、覆盖情况、证据缺口与可信度
- 在长程任务里保持上下文稳定，不因 prompt 过长而退化
- 在最终报告里看到每条关键结论的证据锚点

### 3.2 目标

把当前 Deep Research 升级为一个真正的 **Research Operating System**：

- **计划先行**
- **执行可视**
- **证据可审计**
- **上下文可持续**
- **报告渐进式生成**

### 3.3 成功标准

1. 前端从静态卡片式页面升级为三栏研究工作台
2. 研究流程改为 plan-first，执行过程可见、可中断、可恢复
3. Deep Agents 运行时真正使用 `/plans`、`/scratch`、`/workspace` 等文件上下文
4. comparative / complex 研究默认满足多 provider 覆盖门槛，否则显式展示 coverage gaps
5. 每条关键 claim 可以追溯到 source ledger 和引用集合

## 4. 非目标

本设计明确不做：

- 不保留旧 Deep Research UI 作为长期兼容路径
- 不把系统重新退化成聊天式对话界面
- 不把全部原始证据只存纯 Markdown
- 不在本阶段改造普通聊天、KB Chat 等无关链路
- 不为了兼容旧事件语义而长期保留双轨 artifact 模型

## 5. 设计原则

### 5.1 文件是第一上下文

消息上下文只保留当前最小必要状态；计划、证据、阶段总结、冲突矩阵等都优先写入文件。

### 5.2 Markdown 为控制面，JSON/JSONL 为证据面

- Markdown：计划、阶段摘要、报告草稿、人工可读说明
- JSON/JSONL：原始搜索结果、去重索引、claim-evidence 映射、coverage matrix、conflicts

### 5.3 子代理上下文隔离

每个子代理只负责单一职责；主代理只做编排，不承载所有原始搜索结果。

### 5.4 可信度显式建模

完成条件不再只是“有 findings / citations”，而是同时关注：

- provider 覆盖
- domain 多样性
- claim-evidence 绑定
- conflict 检测
- coverage gaps 显式暴露

### 5.5 默认单一路径

方案 C 的落地前提是 hard cut 到新工作台与新研究编排，不做长期双轨保留。

## 6. 总体架构

系统分为四层：

1. **Mission / Planning Layer**
   - 生成研究目标、任务树、查询地图与执行波次
2. **Execution Layer**
   - 主代理调度子代理执行多源研究
3. **Evidence / Verification Layer**
   - 汇总 provider 结果，构建 claim map、coverage matrix、conflicts
4. **Presentation Layer**
   - 前端工作台实时呈现计划、进度、证据与报告

## 7. Deep Agents 运行时设计

## 7.1 角色划分

### 主代理：Research Conductor

职责：

- 读取 mission 与 plan
- 维护 `write_todos`
- 调度子代理
- 检查 coverage gate
- 决定继续搜索、进入验证或开始综合

### 子代理：Query Strategist

职责：

- 生成 canonical query
- 拆分 aspect queries / comparison queries / verification queries
- 规划 provider 使用策略

### 子代理：Web Investigator

职责：

- 调用 Tavily / SearXNG / Jina
- 生成 query-level source pack
- 记录网页来源摘要与原始数据

### 子代理：Paper Investigator

职责：

- 调用 arXiv
- 建立论文基线与学术补强

### 子代理：Verifier

职责：

- 检查 claim 是否具备足够证据
- 标记 contested claim
- 生成 coverage gaps 与 verification outputs

### 子代理：Synthesizer

职责：

- 按阶段产出综合摘要
- 维护报告草稿
- 收口成最终报告

## 7.2 文件路由

沿用并真正启用以下路径语义：

- `/workspace/`：当前 session 主工作区
- `/plans/`：研究计划、任务树、query map
- `/scratch/`：中间结果、provider 原始输出、阶段综合材料
- `/memories/`：长期模式与偏好
- `/skills/`：按需加载的技能指令

## 8. 文件系统上下文设计

## 8.1 Session 目录结构

```text
/workspace/research/<session_id>/
  00-mission.md
  01-plan.md
  02-query-map.md
  03-coverage.md
  04-report-draft.md

/scratch/research/<session_id>/
  notes/
    subtask-01.md
    subtask-02.md
  evidence/
    tavily/
      q01.summary.md
      q01.raw.json
    searxng/
      q02.summary.md
      q02.raw.json
    jina/
      read-01.summary.md
      read-01.raw.json
    arxiv/
      p01.summary.md
      p01.raw.json
  synthesis/
    wave-01.md
    wave-02.md
  verification/
    claim-map.json
    coverage-matrix.json
    conflicts.json
    source-ledger.json
```

最终收口后的报告不再额外落一个 `05-final-report.md` 工作区文件，而是统一由 finalizer 输出：

- `report_md`
- `report_json`

## 8.2 Markdown 文件规范

Markdown 文件应包含 front matter，至少包括：

- `session_id`
- `phase`
- `subtask_id`（若适用）
- `provider`
- `query`
- `updated_at`

正文至少包括：

- Summary
- Key Findings
- Open Questions
- Next Action

## 8.3 大结果溢写策略

工具返回的大体积结果不直接长期进入上下文：

- 原始结果写入 `raw.json`
- 提炼摘要写入 `summary.md`
- 消息上下文只保留摘要与文件路径

## 9. 搜索编排设计

## 9.1 从单次搜索升级为研究搜索网格

研究搜索改为如下流程：

1. query planning
2. provider fanout
3. evidence packing
4. coverage gate
5. claim verification
6. synthesis

## 9.2 Query 类型

- canonical query
- aspect query
- comparison query
- validation query
- contradiction probe

## 9.3 Provider 分工

- **SearXNG**：广度召回
- **Tavily search / research**：深度网页研究
- **Jina Reader**：页面正文补读
- **arXiv**：论文/学术补强

## 9.4 Coverage Gate

建议门槛：

- **simple**：至少 2 个 web provider，至少 5 个 unique sources
- **comparative**：至少 3 个 web provider，至少 8 个 unique sources
- **complex**：至少 3 个 web provider，且 paper/web 混合，至少 12 个 unique sources

如果未达标：

- 不进入最终完成态
- 显式生成 `coverage.md`
- 前端展示 coverage gaps

## 9.5 Claim Verification

关键 claim 应满足以下之一：

- 两条独立来源支持
- 一条高权威来源 + 一条补充来源支持

若证据冲突：

- claim 标记为 `contested`
- 写入 `conflicts.json`
- 前端 Evidence Ledger 显示冲突状态

## 10. 数据模型设计

## 10.1 Artifact 扩展

新增或重构以下 artifact：

- `mission_md`
- `plan_md`
- `query_map_md`
- `coverage_md`
- `report_draft_md`
- `report_md`
- `claim_map_json`
- `coverage_matrix_json`
- `conflicts_json`
- `source_ledger_json`

## 10.2 事件扩展

新增事件类型：

- `research.plan.generated`
- `research.query_map.generated`
- `research.wave.started`
- `research.provider.coverage.updated`
- `research.claim.verified`
- `research.claim.contested`
- `research.report.section.updated`
- `research.gate.blocked`
- `research.gate.passed`

## 11. 前端工作台设计

## 11.1 布局

采用 **顶部状态条 + 三栏布局**：

- 顶栏：Mission Control
- 左栏：Plan Rail
- 中栏：Report Canvas
- 右栏：Evidence Ledger

## 11.2 顶栏：Mission Control

展示：

- 当前研究问题
- 当前 phase
- 运行状态
- provider 覆盖进度
- 可信度状态
- 中断 / 恢复 / 导出

## 11.3 左栏：Plan Rail

展示：

- 研究目标
- 任务树
- 当前波次
- 已完成 / 进行中 / 阻塞
- parked items
- coverage gaps

## 11.4 中栏：Report Canvas

展示：

- 当前执行摘要
- 关键发现
- claim blocks
- report draft
- final report

## 11.5 右栏：Evidence Ledger

展示：

- provider 覆盖
- query 轨迹
- source list
- claim 证据绑定
- 冲突项
- 原文快照入口

## 12. 交互与动画设计

## 12.1 交互节奏

### 阶段 A：Plan-first

用户提交问题后：

1. 先生成 plan
2. 展示研究任务拆解
3. 展示预计搜索面
4. 再进入执行

### 阶段 B：Execution

执行中：

- 子任务卡片状态流转
- provider coverage 实时更新
- source ledger 增量刷新
- report canvas 按阶段吸收发现

### 阶段 C：Synthesis

报告渐进式生成：

- skeleton
- section draft
- claim-evidence binding
- final report

## 12.2 动效原则

- 优先复用现有 MD3 motion
- 必须兼容 `prefers-reduced-motion`
- 动效服务于状态感知，不服务于装饰

建议动效：

1. Composer morph 到 mission capsule
2. Plan step reveal
3. Coverage bar pulse
4. Evidence dock slide-in
5. Canvas section height transition
6. Reduced-motion 下退化为淡入或无位移

## 13. 路线图

## Phase 1：Research OS backend skeleton

目标：

- 建立 session 文件树
- 启用 `/plans`、`/scratch` 文件读写
- 增加 source ledger / claim map / coverage matrix

## Phase 2：Search mesh & trust gates

目标：

- query planning
- provider fanout
- coverage gate
- conflict detection
- 质量分升级

## Phase 3：New workspace shell

目标：

- 新顶栏
- 三栏布局
- plan rail / report canvas / evidence ledger

## Phase 4：Animation & polishing

目标：

- 动效联动
- reduced-motion 校验
- 视觉统一

## Phase 5：Verification closure

目标：

- 后端 pytest / ruff
- 前端 vitest / typecheck / build
- 真实 session smoke
- artifact existence checks

## 14. 风险与对策

### 风险 1：方案 C 改动面过大

对策：

- 分 phase 落地
- 每 phase 单独验收
- 不一次性全量 hard cut

### 风险 2：文件过多导致管理复杂

对策：

- 统一命名规范
- 严格区分控制面与证据面
- 只让 agent 加载当前所需文件

### 风险 3：可信度门槛导致耗时增加

对策：

- complexity 分级门槛
- 支持显式 coverage gap 收口
- 不强行无限搜索

## 15. 验收标准

### 产品验收

- 用户能看到计划、执行、证据、报告四层联动

### 可信度验收

- comparative / complex 问题默认达成 provider breadth gate
- 不满足时明确暴露 coverage gap

### 上下文验收

- 大结果通过文件溢写管理
- 主代理与子代理依赖文件恢复上下文

### 工程验收

- 不保留旧工作台长期双轨
- 数据合同可测试
- artifacts 可回放
- smoke 可验证真实文件产物

## 16. 决策结论

采用方案 C，把当前 Deep Research 从“研究会话页”升级为 **Deep Research OS**。

该方案成立的关键前提：

1. 接受 plan-first
2. 接受文件系统作为第一上下文
3. 接受可信度结构显式化
4. 接受最终 hard cut 到单一路径

在以上前提下，该方案可作为后续实施规划与分 phase 交付的唯一设计基线。
