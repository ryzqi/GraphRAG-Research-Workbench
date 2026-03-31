# Task Todo - Medium

## Project Completion Snapshot
- Project Mode: Multi-phase
- Current State: Completed
- Final Deliverable: 8 个性能大类别已全部按顺序完成，并保留阶段归档与独立提交链
- Final Archive Reference:
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-01-waterfalls.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-02-bundle-size.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-03-server-side.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-04-client-data.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-05-rerender.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-06-rendering.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-07-javascript.md`
  - `archive/perf-phases/TASK_TODO_MEDIUM.phase-08-advanced.md`

## Final Checklist
### 1. Phase delivery chain
- [x] Phase 1 完成并提交 `8e7e152`
- [x] Phase 2 完成并提交 `7f5eee0`
- [x] Phase 3 完成并提交 `7fd0750`
- [x] Phase 4 完成并提交 `6df521f`
- [x] Phase 5 完成并提交 `53a8dd2`
- [x] Phase 6 完成并提交 `567e1af`
- [x] Phase 7 完成并提交 `830477f`
- [x] Phase 8 完成并提交 `b281944`

### 2. Final verification
- [x] `npm run typecheck`
- [x] `npm run lint`
- [x] `npx vitest run src/services/http.test.ts src/services/routePrefetch.test.ts src/services/researchWorkbench.test.ts`
- [x] `npm run build`
- [x] `git status --short`

### 3. Final repo hygiene
- [x] 归档补齐到 Phase 8
- [x] 工作区干净
- [x] 线长豁免路径已与 `src/theme/md3Theme.ts` 对齐
