# Findings

## 2026-04-10 初始基线

- `Agent Reach doctor` 结果：GitHub、YouTube、Reddit、V2EX、RSS/Atom、全网语义搜索、任意网页 7/7 可用。
- 仓库当前为 dirty worktree，且未提交改动主要位于 deep research runtime、prompt 模板与研究后处理链路；后续提交时必须避免误回滚。
- `README.md` 给出的 Deep Research 当前事实源：
  - 统一业务主标识为 `session_id`
  - 前端展示优先消费 `presentation_snapshot`
  - Deep Research API 契约见 `docs/api_contract_research.md`
- 代码检索结果显示：
  - 入口：`backend/src/app/services/research_service.py::execute_session`
  - 运行时构建：`backend/src/app/services/deep_research_runtime.py::build_deep_research_runtime_runner` / `create_deep_research_runtime`
  - DeepAgents 创建：`create_deep_agent(**agent_kwargs)`
  - 上下文注入：workspace context docs、runtime skills、session bootstrap workspace files、prompt 模板
  - Prompt 加载器：`backend/src/app/prompts/loader.py`

## 待补充

- 任务 1 外部调研结论与当前实现差距
- 任务 2 外部调研结论与当前实现差距
- 任务 3 外部调研结论与当前实现差距
- 每阶段测试红/绿证据与提交 SHA

## 2026-04-10 任务 1 外部调研：上下文管理

- Anthropic long-context / context-management 方向资料的共同点：
  - 长上下文不能只靠“全塞进去”，需要显式结构化与分层。
  - 应给模型稳定的阅读顺序和上下文索引，而不是让它在大量文件里自行摸索。
  - 大块资料更适合外置成文件并配摘要/索引，避免主提示被噪声淹没。
- OpenAI 关于内部 data agent 的经验：
  - 运行时上下文应分层，原始日志/元数据/结果不应直接混在同一层让模型扫描。
  - 需要把“高价值、可直接行动的信息”提到近处，把原始大对象放到更远层按需读取。
- LangGraph memory 概念文档的要点：
  - thread-scoped 短期上下文与跨线程长期记忆应明确分离。
  - procedural memory（规则/技能/提示）不应与 semantic / episodic factual context 混为一层。

## 2026-04-10 任务 1 当前实现差距假设

- 当前 `DeepResearchRuntimeRunner.run_session()` 会把 `workspace files + runtime skills + bootstrap artifacts` 一起放进 `request_files`。
- 当前 `_build_runtime_prompt()` 直接把 `sorted(request_files)` 全量写进 `workspace_paths_block`。
- 这导致 prompt 中的“优先阅读 workspace 文档”实际混入：
  - `/skills/...`
  - `/scratch/...`
  - 其他仅供溢写/恢复使用的文件
- 该混层与外部最佳实践相悖，优先修复方向：
  - 为 runtime 生成显式上下文导览/索引文件
  - prompt 只暴露优先阅读的上下文层，不再把技能文件和 scratch 溢写文件混入首层阅读列表

## 2026-04-10 任务 1 已落地实现

- 在 `backend/src/app/services/research_runtime_context.py` 新增：
  - `ResearchRuntimeContextGuide`
  - `build_runtime_context_guide(...)`
  - guide 中显式区分：
    - primary context layer：`/workspace/context/*` 与 `/workspace/research/*`
    - procedural skills：`/skills/*`
    - scratch / spill：`/scratch/*`
- 在 `backend/src/app/services/deep_research_runtime.py` 中：
  - `run_session()` 先构造 `layout`
  - 在注入 skills 与 session bootstrap 文件后生成 `runtime_context_guide.md`
  - prompt 的 `workspace_paths_block` 改为只使用 `context_guide.priority_paths`
  - request 的 `files` 仍保留全量，不影响按需读取能力

## 2026-04-10 任务 1 验证证据

- 红灯：
  - `cd F:\毕设\code\backend; uv run pytest tests/test_deep_research_runtime.py -q`
  - 初次新增测试失败：
    - `test_runner_injects_runtime_context_guide_file`
    - `test_runner_prompt_lists_only_priority_context_files`
- 绿灯：
  - `cd F:\毕设\code\backend; uv run pytest tests/test_deep_research_runtime.py -q` -> `7 passed`
  - `cd F:\毕设\code\backend; uv run pytest tests/test_research_workspace_files.py -q` -> `2 passed`
