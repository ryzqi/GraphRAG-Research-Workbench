# Task Todo - Fine

## Project / Phase Context
- Current Phase: Phase 5 - Re-render Optimization
- Current Phase Inputs:
  - `frontend/src/views/KbChatPage.tsx`
  - `frontend/src/views/ModelConfigPage.tsx`
  - `frontend/src/components/EvidenceList.tsx`
  - `frontend/src/components/KnowledgeBaseSelector.tsx`
- Phase Goal: 让派生状态在 render 阶段完成，移除对 primitive 值无收益的 memo 包装。

## Part 1: Current phase requirement and scope
### 1.1 Capture the executable objective for this phase
- [x] Task: 明确 Phase 5 的文件级目标

### 1.2 Enumerate current-phase dependencies and prerequisites
- [x] Task: 明确验证命令与提权约束

## Part 2: Current phase research and decomposition
### 2.1 Inspect relevant context in detail for this phase
- [x] Task: 固化重渲染热点审计结论

### 2.2 Break the current phase into executable units
- [x] Task: 拆解为派生状态收口与 primitive `useMemo` 清理

## Part 3: Current phase execution
### 3.1 Complete the first executable slice of this phase
- [x] Task: `KbChatPage.tsx` / `ModelConfigPage.tsx` 去掉同步 effect

### 3.2 Complete remaining executable slices of this phase
- [x] Task: `EvidenceList.tsx` / `KnowledgeBaseSelector.tsx` 移除 primitive `useMemo`

## Part 4: Verification and transition
### 4.1 Verify completed outputs for this phase
- [x] Task: 执行 Phase 5 验证
- Notes:
  - `npm run typecheck` 通过
  - 定向 `eslint` 通过
  - `npm run build` 通过

### 4.2 Reconcile phase completion and prepare the next step
- [x] Task: 提交 Phase 5 commit
- Notes: 已提交 `53a8dd2`
