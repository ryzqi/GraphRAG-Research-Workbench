import type { AlertColor } from '@mui/material';

import type { BatchStatus, DocStatus, ManifestSourceType } from '../../services/ingestionBatches';
import type { BootstrapSubmissionStatus } from '../../services/bootstrapSubmissions';

export type IngestionChipColor = 'default' | 'warning' | 'success' | 'error' | 'info';
export type LiveStreamStatus = 'idle' | 'connecting' | 'live' | 'fallback_polling';
export type DocPresentationStatus = 'processing' | 'succeeded' | 'failed' | 'canceled';

export interface IngestionDocStateLike {
  status: DocStatus;
  error_code: string | null;
}

export interface IngestionBatchSummaryLike {
  succeeded_docs: number;
  failed_docs: number;
  canceled_docs: number;
  succeeded_chunks: number;
  docs: IngestionDocStateLike[];
}

export interface IngestionSummaryMetrics {
  succeededDocs: number;
  failedDocs: number;
  canceledDocs: number;
  processingDocs: number;
  succeededChunks: number;
}

export function sourceTypeLabel(sourceType: ManifestSourceType | 'upload'): string {
  switch (sourceType) {
    case 'text':
      return '文本';
    case 'url':
      return 'URL';
    case 'file':
      return '文件';
    case 'upload':
      return '上传文件';
    default:
      return sourceType;
  }
}

export function batchStatusLabel(status: BatchStatus): string {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'processing':
      return '处理中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'canceled':
      return '已取消';
    default:
      return status;
  }
}

export function batchStatusColor(status: BatchStatus): IngestionChipColor {
  switch (status) {
    case 'queued':
      return 'default';
    case 'processing':
      return 'warning';
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'canceled':
      return 'default';
    default:
      return 'default';
  }
}

export function bootstrapStatusLabel(status: BootstrapSubmissionStatus): string {
  switch (status) {
    case 'queued_upload':
      return '等待上传';
    case 'queued':
      return '排队中';
    case 'running':
      return '处理中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    default:
      return status;
  }
}

export function bootstrapStatusColor(status: BootstrapSubmissionStatus): IngestionChipColor {
  switch (status) {
    case 'queued_upload':
      return 'info';
    case 'queued':
      return 'default';
    case 'running':
      return 'warning';
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    default:
      return 'default';
  }
}

export function isDocFailed(doc: IngestionDocStateLike): boolean {
  return doc.status === 'failed';
}

export function isDocCanceled(doc: IngestionDocStateLike): boolean {
  return doc.status === 'canceled';
}

export function docPresentationStatus(doc: IngestionDocStateLike): DocPresentationStatus {
  if (doc.status === 'queued' || doc.status === 'processing') {
    return 'processing';
  }
  if (isDocCanceled(doc)) {
    return 'canceled';
  }
  if (isDocFailed(doc)) {
    return 'failed';
  }
  return 'succeeded';
}

export function docPresentationLabel(status: DocPresentationStatus): string {
  switch (status) {
    case 'processing':
      return '处理中';
    case 'succeeded':
      return '成功';
    case 'failed':
      return '失败';
    case 'canceled':
      return '已取消';
    default:
      return status;
  }
}

export function docPresentationColor(status: DocPresentationStatus): IngestionChipColor {
  switch (status) {
    case 'processing':
      return 'warning';
    case 'succeeded':
      return 'success';
    case 'failed':
      return 'error';
    case 'canceled':
      return 'default';
    default:
      return 'default';
  }
}

export function buildBatchSummaryMetrics(batch: IngestionBatchSummaryLike): IngestionSummaryMetrics {
  const processingDocs = batch.docs.filter((doc) => docPresentationStatus(doc) === 'processing').length;
  return {
    succeededDocs: batch.succeeded_docs,
    failedDocs: batch.failed_docs,
    canceledDocs: batch.canceled_docs,
    processingDocs,
    succeededChunks: batch.succeeded_chunks,
  };
}

export function formatIngestionSummaryText(metrics: IngestionSummaryMetrics): string {
  return (
    '文档：成功 ' +
    metrics.succeededDocs +
    ' / 失败 ' +
    metrics.failedDocs +
    ' / 取消 ' +
    metrics.canceledDocs +
    ' / 处理中 ' +
    metrics.processingDocs +
    ' / 分块 ' +
    metrics.succeededChunks
  );
}

export function streamHintText(options: {
  enabled: boolean;
  streamStatus: LiveStreamStatus;
  fallbackIntervalMs: number;
}): string | null {
  if (!options.enabled) {
    return null;
  }
  if (options.streamStatus === 'connecting') {
    return '正在建立实时状态连接…';
  }
  if (options.streamStatus === 'live') {
    return '实时状态已连接。';
  }
  if (options.streamStatus === 'fallback_polling') {
    return `实时连接中断，已切换轮询（每 ${Math.round(options.fallbackIntervalMs / 1000)} 秒）。`;
  }
  return '正在等待处理状态更新。';
}

export function streamHintSeverity(streamStatus: LiveStreamStatus): AlertColor {
  if (streamStatus === 'fallback_polling') {
    return 'warning';
  }
  return 'info';
}
