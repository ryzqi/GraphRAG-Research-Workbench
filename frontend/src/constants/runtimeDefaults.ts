/**
 * 前端运行时默认值。
 *
 * 这些值对应当前仓库里真正生效的轮询/重试行为：
 * - bootstrap / ingestion 常态轮询：交互式状态页默认每 2s 刷新一次；
 * - ingestion live：主链路优先走 SSE，断流后按 1s -> 2s -> 5s 回退，并放大 2x 重连等待；
 * - export：用户主动等待一次性导出任务时，按 1s * 60 次提供约 60s 的默认等待窗口。
 */

/** 交互式状态查询（bootstrap / ingestion）默认轮询间隔。 */
export const DEFAULT_STATUS_POLLING_INTERVAL_MS = 2_000;

/**
 * Ingestion SSE 断流后的回退轮询步进。
 * 先快后慢，优先快速恢复，再把稳态负载收敛到 5s。
 */
export const INGESTION_STREAM_FALLBACK_POLLING_STEPS_MS = [1_000, 2_000, 5_000] as const;

/** Ingestion SSE 断流后，下一次主动重连前的等待倍率。 */
export const INGESTION_STREAM_RETRY_MULTIPLIER = 2;

/** 导出任务默认轮询间隔。 */
export const DEFAULT_EXPORT_POLL_INTERVAL_MS = 1_000;

/** 导出任务默认最大轮询次数（约等于 60s 等待窗口）。 */
export const DEFAULT_EXPORT_POLL_MAX_ATTEMPTS = 60;
