import type { PublicRuntimeConfigRead } from '../services/runtimeConfig';

type PublicRuntimeBehaviorConfig = Pick<
  PublicRuntimeConfigRead,
  | 'status_polling_interval_ms'
  | 'ingestion_stream_fallback_polling_steps_ms'
  | 'ingestion_stream_retry_multiplier'
  | 'export_poll_interval_ms'
  | 'export_poll_max_attempts'
  | 'server_prefetch_cache_revalidate_seconds'
  | 'download_allowed_hosts'
>;

/**
 * 前端运行时默认值。
 *
 * 这些值仅作为 `runtime-config` 尚未加载完成时的保守回退；
 * 一旦后端公开配置可用，应始终以后端下发值为准。
 */
export const DEFAULT_STATUS_POLLING_INTERVAL_MS = 2_000;
export const INGESTION_STREAM_FALLBACK_POLLING_STEPS_MS = [1_000, 2_000, 5_000] as const;
export const INGESTION_STREAM_RETRY_MULTIPLIER = 2;
export const DEFAULT_EXPORT_POLL_INTERVAL_MS = 2_000;
export const DEFAULT_EXPORT_POLL_MAX_ATTEMPTS = 60;
export const DEFAULT_SERVER_PREFETCH_CACHE_REVALIDATE_SECONDS = 30;
export const DEFAULT_DOWNLOAD_ALLOWED_HOSTS: readonly string[] = [];

function normalizePositiveNumber(value: number | undefined, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}

function normalizeAllowedHosts(hosts: readonly string[] | undefined): string[] {
  const source = hosts && hosts.length > 0 ? hosts : DEFAULT_DOWNLOAD_ALLOWED_HOSTS;
  const normalized = source
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return Array.from(new Set(normalized));
}

export function getStatusPollingIntervalMs(
  config?: PublicRuntimeBehaviorConfig | null
): number {
  return normalizePositiveNumber(
    config?.status_polling_interval_ms,
    DEFAULT_STATUS_POLLING_INTERVAL_MS
  );
}

export function getIngestionStreamFallbackPollingStepsMs(
  config?: PublicRuntimeBehaviorConfig | null
): readonly number[] {
  const source = config?.ingestion_stream_fallback_polling_steps_ms;
  if (!Array.isArray(source) || source.length === 0) {
    return INGESTION_STREAM_FALLBACK_POLLING_STEPS_MS;
  }

  const normalized = source.filter(
    (item): item is number => typeof item === 'number' && Number.isFinite(item) && item > 0
  );
  return normalized.length > 0 ? normalized : INGESTION_STREAM_FALLBACK_POLLING_STEPS_MS;
}

export function getIngestionStreamRetryMultiplier(
  config?: PublicRuntimeBehaviorConfig | null
): number {
  return normalizePositiveNumber(
    config?.ingestion_stream_retry_multiplier,
    INGESTION_STREAM_RETRY_MULTIPLIER
  );
}

export function getExportPollIntervalMs(
  config?: PublicRuntimeBehaviorConfig | null
): number {
  return normalizePositiveNumber(
    config?.export_poll_interval_ms,
    DEFAULT_EXPORT_POLL_INTERVAL_MS
  );
}

export function getExportPollMaxAttempts(
  config?: PublicRuntimeBehaviorConfig | null
): number {
  return normalizePositiveNumber(
    config?.export_poll_max_attempts,
    DEFAULT_EXPORT_POLL_MAX_ATTEMPTS
  );
}

export function getServerPrefetchCacheRevalidateSeconds(
  config?: PublicRuntimeBehaviorConfig | null
): number {
  return typeof config?.server_prefetch_cache_revalidate_seconds === 'number' &&
    Number.isFinite(config.server_prefetch_cache_revalidate_seconds) &&
    config.server_prefetch_cache_revalidate_seconds >= 0
    ? config.server_prefetch_cache_revalidate_seconds
    : DEFAULT_SERVER_PREFETCH_CACHE_REVALIDATE_SECONDS;
}

export function getDownloadAllowedHosts(
  config?: PublicRuntimeBehaviorConfig | null
): string[] {
  return normalizeAllowedHosts(config?.download_allowed_hosts);
}
