# Frontend Migration Status

## 状态

- 迁移已完成（2026-02-08）：前端已统一为 `frontend/` 下的 Next.js App Router 实现。
- 旧的 Vite 前端代码与依赖已移除，不再保留并行目录。

## 当前前端入口

```powershell
cd frontend
npm install
npm run dev
```

- 本地开发端口：`3000`
- 构建命令：`npm run build`
- 类型检查：`npm run typecheck`

## 兼容与实现说明

- 路由已迁移到 App Router（`src/app/**`）。
- 原 `react-router-dom` 兼容层已删除，统一使用 `next/navigation` 与 `next/link`。
- 原 `src/pages` 已重命名为 `src/views`，避免与 Next Pages Router 目录冲突。

## 备注

该文档用于记录迁移结果，原 Stage 1 并行迁移方案已失效。
