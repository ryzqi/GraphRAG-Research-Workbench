# Deep Agents 最新用法快照（2026-03-26）

## 目标

基于 **LangChain / LangGraph / Deep Agents 官方文档 MCP** 与官方文档 / 官方仓库，提炼当前 Deep Agents 在本仓库场景下最重要、最可执行的用法结论。

## 查询事实源

### 使用的 LangChain 文档 MCP 查询主题

- `Deep Agents latest Python usage create_deep_agent ...`
- `Deep Agents Python backends FilesystemBackend StateBackend StoreBackend CompositeBackend ...`
- `Deep Agents Python subagents customization interrupt_on human approval ...`
- 额外补充查询：overview / customization / context engineering / long-term-memory / subagents / streaming / skills

### 补充验证源

- 官方文档：
  - <https://docs.langchain.com/oss/python/deepagents/overview>
  - <https://docs.langchain.com/oss/python/deepagents/customization>
  - <https://docs.langchain.com/oss/python/deepagents/context-engineering>
  - <https://docs.langchain.com/oss/python/deepagents/backends>
  - <https://docs.langchain.com/oss/python/deepagents/subagents>
  - <https://docs.langchain.com/oss/python/deepagents/human-in-the-loop>
  - <https://docs.langchain.com/oss/python/deepagents/long-term-memory>
  - <https://docs.langchain.com/oss/python/deepagents/skills>
  - <https://docs.langchain.com/oss/python/deepagents/streaming>
- 官方仓库 latest release：`langchain-ai/deepagents` `deepagents==0.5.0a2`，发布时间 2026-03-23。

## 一、当前官方能力面

官方 overview / customization / release 信息组合起来，当前 Deep Agents 可直接视为一个 **agent harness**：

- planning：TodoListMiddleware
- filesystem：FilesystemMiddleware
- subagents：SubAgentMiddleware
- summarization / context offloading：SummarizationMiddleware
- long-term memory：MemoryMiddleware
- skills：SkillsMiddleware
- HITL：HumanInTheLoopMiddleware
- streaming：原生支持 main agent + subagents streaming
- persistence / resume：基于 LangGraph runtime + checkpointer

**结论：** 对我们这种“长时、多阶段、可恢复、要文件与工件”的研究系统，Deep Agents 适合作为 runtime harness；但不适合承载全部业务状态机。业务层仍应保留 session / event / artifact / audit / gate / API contract。

## 二、`create_deep_agent` 当前核心配置面

官方 customization 页面当前明确给出以下核心配置面：

- `model`
- `tools`
- `system_prompt`
- `middleware`
- `subagents`
- `backends`
- `interrupt_on`
- `skills`
- `memory`

结合 release 信息，当前值得注意的最新点有：

1. **`subagents` 已经是一等顶层配置面。**  
   release 里出现了“merge async subagents and subagents into single top level param”，说明官方正在收敛子代理配置方式。

2. **Backends 已成为 Deep Agents 的关键抽象。**  
   官方把 `StateBackend / FilesystemBackend / StoreBackend / CompositeBackend` 单独抽成核心能力页，不再只是文件读写细节。

3. **HITL 依赖 `interrupt_on + checkpointer`。**  
   文档明确写了：如果要 human-in-the-loop，checkpointer 是必需条件。

4. **Streaming 已经不仅是主代理 token stream，而是 subgraph-aware streaming。**  
   当前官方 streaming 文档要求在流式消费时开启 `subgraphs=True`，并用 `namespace` 区分 main agent 与 subagents 事件。

5. **官方 release 已显式包含 trace / async subagents / sandbox / multimodal file read 等增强。**  
   这意味着我们在设计里不应再把 Deep Agents 当成“只有 todo + file + task 三个工具”的旧版本认知。

## 三、当前最推荐的用法模式

### 1. 把 Deep Agents 用作 runtime harness，而不是整个产品状态机

**推荐：**
- Deep Agents 负责：计划执行、文件上下文、子代理、上下文压缩、skills、memory、HITL、subgraph streaming
- 业务层负责：`session_id`、DB 三表、SSE 映射、恢复幂等、审计、门禁、工件读取

**不推荐：**
- 把审批状态、数据库写入、发布门禁全塞回代理内部
- 用 Deep Agents 取代所有显式服务层契约

### 2. 显式传入 model，不依赖默认值

customization 页说明当前默认模型为 `claude-sonnet-4-6`。对生产系统而言，建议：

- 主代理模型显式配置
- 子代理模型显式配置（可更便宜）
- 超时 / 重试显式配置

**原因：** 当前 Deep Agents 仍在 pre-1.0 快速迭代，不应把默认模型与默认超时当成稳定契约。

### 3. 通过 `CompositeBackend` 明确划分“线程内临时文件”和“跨线程持久记忆”

官方 backends / long-term-memory / context-engineering 的组合结论非常明确：

- `StateBackend`：线程内、短期、临时
- `StoreBackend`：跨线程、长期、持久
- `CompositeBackend`：按路径路由

**对本仓库的推荐路由：**

- `/workspace/`：当前任务的工作区输入
- `/scratch/`：运行中临时草稿 / 中间笔记
- `/plans/`：brief / plan snapshot / source bundle 草稿
- `/memories/`：长期指令 / 用户偏好 / 研究方法记忆
- `/skills/`：技能目录

**结论：** 业务数据库与 agent 虚拟文件系统必须分开；DB 是业务事实源，backend 只是代理上下文与工件加工层。

### 4. memory 与 skills 要分层使用

官方 context-engineering / skills 页面给出的最佳实践非常清楚：

- **memory**：始终注入，适合最小且稳定的项目规范 / 用户偏好 / AGENTS
- **skills**：按需 progressive disclosure，适合详细流程、专门工作流、额外脚本 / 参考资料

**对本仓库的推荐：**

- memory 只放最小强约束：研究模式原则、source routing 纪律、citation 纪律、安全边界
- skills 放具体流程：KB research、web research、paper research、citation finalization

**不推荐：**
- 把大段手册、长 SOP 全塞进 memory
- 做多个高度重叠的 skills，让模型难以选择

### 5. subagents 的目标是 context isolation，不是角色表演

官方 subagents 页与 Anthropic 文章都支持同一个结论：

- 优先用 `general-purpose` 子代理做上下文隔离
- 只有在确有工具 / prompt / 输出契约差异时才引入 specialized subagents
- 返回主代理的结果应尽量 concise，避免把原始噪音全带回主上下文

**对本仓库的推荐子代理集：**

- `general-purpose`：默认隔离并行研究单元
- `kb-researcher`：只接 KB / 内部知识源工具
- `web-researcher`：只接公网搜索 / 网页抽取工具
- `paper-researcher`：只接 arXiv / 论文元数据工具
- `citation-finalizer`：只做 citation 规范化与结构化输出

### 6. HITL 只拦危险动作，不拦普通检索动作

官方 human-in-the-loop 文档的核心结论：

- `interrupt_on` 用来配置需要审批的工具
- 可按 tool 配 `approve / edit / reject`
- 恢复使用 `Command(resume={"decisions": [...]})`
- 必须复用相同 `thread_id`

**对本仓库的推荐：**

- 默认不拦 `search` / `read` / `arxiv_fetch` / `kb_lookup`
- 只拦：`execute`、敏感写文件、外发请求、潜在高成本动作
- 研究模式如果首期不开放 `execute`，则 HITL 主要留给“计划确认 / 中断 / 恢复”业务层，而不是 runtime 工具层

### 7. 流式输出必须按 `namespace` 组织前端 UI

官方 streaming 页明确指出：

- `agent.stream(..., stream_mode="updates", subgraphs=True, version="v2")`
- 事件带 `namespace`
- 可区分 main agent 与 subagents
- 可流式显示 tool calls、progress、tokens、自定义 updates

**对本仓库的推荐：**

- SSE 层保留 `namespace` / `subagent_name` / `phase` / `event_type`
- 前端 timeline 按 namespace 分组
- main agent 显示宏观 phase，subagent 显示“谁在查什么、产出了什么压缩结果”

### 8. 长时研究应主动使用 context compression，而不是等爆窗

官方 context-engineering / customization / release 都说明了 Deep Agents 已把 summarization / offloading 当成核心能力。

**对本仓库的推荐：**

- 对大网页 / 大工具结果启用文件落盘与引用返回
- 在阶段切换点（scope 完成、source bundle 收口、finalizer 前）主动做中间压缩
- 避免主代理长期保留所有原始网页正文

## 四、面向本仓库的最小推荐代码形态（示意）

```python
from deepagents import create_deep_agent
from deepagents.backends import StateBackend, StoreBackend, CompositeBackend
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()

backend = CompositeBackend(
    routes={
        "/workspace": StateBackend(),
        "/scratch": StateBackend(),
        "/plans": StateBackend(),
        "/memories": StoreBackend(store=memory_store),
        "/skills": StoreBackend(store=memory_store),
    }
)

agent = create_deep_agent(
    name="deep-research-runtime",
    model=supervisor_model,
    subagent_model=worker_model,
    tools=[kb_lookup, web_search, arxiv_search, arxiv_fetch, finalize_report],
    system_prompt=RESEARCH_RUNTIME_PROMPT,
    subagents=[
        general_purpose_subagent,
        kb_subagent,
        web_subagent,
        paper_subagent,
        citation_subagent,
    ],
    backend=backend,
    checkpointer=checkpointer,
    skills=["/skills/"],
    memory=["/memories/AGENTS.md"],
    interrupt_on={
        "execute": {"allowed_decisions": ["approve", "reject"]},
    },
)
```

> 说明：以上是结构示意，不是对当前仓库的直接可运行代码。

## 五、与当前提案相比，必须新增或收紧的点

1. **明确 `checkpointer` 是 runtime 标配，不只是可选项。**  
   否则无法稳定支持恢复 / HITL / thread continuity。

2. **明确 SSE 需要映射 subgraph namespace。**  
   当前如果只映射通用 token / status，会丢失 Deep Agents streaming 的关键价值。

3. **明确 memory 与 skills 的职责边界。**  
   否则很容易把大块说明塞进 memory，导致 prompt 膨胀。

4. **明确 `CompositeBackend` 路由与路径前缀。**  
   这是 runtime 能否长期稳定运行的基础设施前提。

5. **明确主 / 子代理模型分层策略。**  
   否则成本门禁很难真正落地。

6. **明确 runtime 阶段要有中间压缩与 source bundle 收口。**  
   不能只靠 finalizer 做最后一轮整理。

## 六、参考链接

- Deep Agents overview: <https://docs.langchain.com/oss/python/deepagents/overview>
- Customize Deep Agents: <https://docs.langchain.com/oss/python/deepagents/customization>
- Context engineering: <https://docs.langchain.com/oss/python/deepagents/context-engineering>
- Backends: <https://docs.langchain.com/oss/python/deepagents/backends>
- Subagents: <https://docs.langchain.com/oss/python/deepagents/subagents>
- Human-in-the-loop: <https://docs.langchain.com/oss/python/deepagents/human-in-the-loop>
- Long-term memory: <https://docs.langchain.com/oss/python/deepagents/long-term-memory>
- Skills: <https://docs.langchain.com/oss/python/deepagents/skills>
- Streaming: <https://docs.langchain.com/oss/python/deepagents/streaming>
- Deep Agents latest release (`deepagents==0.5.0a2`): <https://github.com/langchain-ai/deepagents/releases/tag/deepagents%3D%3D0.5.0a2>
