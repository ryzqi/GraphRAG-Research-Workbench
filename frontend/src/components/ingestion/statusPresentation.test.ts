import { describe, expect, it } from 'vitest';

import {
  batchStatusColor,
  batchStatusLabel,
  bootstrapStatusColor,
  bootstrapStatusLabel,
  buildBatchSummaryMetrics,
  docPresentationColor,
  docPresentationLabel,
  docPresentationStatus,
  formatIngestionSummaryText,
  sourceTypeLabel,
  streamHintSeverity,
  streamHintText,
} from './statusPresentation';

describe('statusPresentation', () => {
  it('maps batch status labels and colors', () => {
    expect(batchStatusLabel('processing')).toBe('处理中');
    expect(batchStatusLabel('completed')).toBe('已完成');
    expect(batchStatusColor('processing')).toBe('warning');
    expect(batchStatusColor('completed')).toBe('success');
  });

  it('maps bootstrap status labels and colors', () => {
    expect(bootstrapStatusLabel('queued_upload')).toBe('等待上传');
    expect(bootstrapStatusLabel('queued')).toBe('排队中');
    expect(bootstrapStatusLabel('running')).toBe('处理中');
    expect(bootstrapStatusLabel('completed')).toBe('已完成');
    expect(bootstrapStatusLabel('failed')).toBe('失败');

    expect(bootstrapStatusColor('queued_upload')).toBe('info');
    expect(bootstrapStatusColor('queued')).toBe('default');
    expect(bootstrapStatusColor('running')).toBe('warning');
    expect(bootstrapStatusColor('completed')).toBe('success');
    expect(bootstrapStatusColor('failed')).toBe('error');
  });

  it('classifies document presentation statuses', () => {
    expect(docPresentationStatus({ status: 'processing', error_code: null })).toBe('processing');
    expect(docPresentationStatus({ status: 'completed', error_code: null })).toBe('succeeded');
    expect(docPresentationStatus({ status: 'completed', error_code: 'DOC_PARSE_FAILED' })).toBe('failed');
    expect(docPresentationStatus({ status: 'completed', error_code: 'DOC_CANCELED' })).toBe('canceled');
  });

  it('maps document presentation labels and colors', () => {
    expect(docPresentationLabel('processing')).toBe('处理中');
    expect(docPresentationLabel('succeeded')).toBe('成功');
    expect(docPresentationLabel('failed')).toBe('失败');
    expect(docPresentationLabel('canceled')).toBe('已取消');

    expect(docPresentationColor('processing')).toBe('warning');
    expect(docPresentationColor('succeeded')).toBe('success');
    expect(docPresentationColor('failed')).toBe('error');
    expect(docPresentationColor('canceled')).toBe('default');
  });

  it('builds batch summary metrics with processing count from docs', () => {
    const metrics = buildBatchSummaryMetrics({
      succeeded_docs: 3,
      failed_docs: 1,
      canceled_docs: 2,
      succeeded_chunks: 48,
      docs: [
        { status: 'processing', error_code: null },
        { status: 'completed', error_code: null },
        { status: 'completed', error_code: 'DOC_PARSE_FAILED' },
      ],
    });

    expect(metrics).toEqual({
      succeededDocs: 3,
      failedDocs: 1,
      canceledDocs: 2,
      processingDocs: 1,
      succeededChunks: 48,
    });
    expect(formatIngestionSummaryText(metrics)).toBe(
      '文档：成功 3 / 失败 1 / 取消 2 / 处理中 1 / 分块 48'
    );
  });

  it('returns stream hint text and severity', () => {
    expect(streamHintText({ enabled: false, streamStatus: 'live', fallbackIntervalMs: 0 })).toBeNull();
    expect(streamHintText({ enabled: true, streamStatus: 'connecting', fallbackIntervalMs: 0 })).toBe(
      '正在建立实时状态连接…'
    );
    expect(streamHintText({ enabled: true, streamStatus: 'live', fallbackIntervalMs: 0 })).toBe(
      '实时状态已连接。'
    );
    expect(streamHintText({ enabled: true, streamStatus: 'fallback_polling', fallbackIntervalMs: 3000 })).toBe(
      '实时连接中断，已切换轮询（每 3 秒）。'
    );
    expect(streamHintText({ enabled: true, streamStatus: 'idle', fallbackIntervalMs: 0 })).toBe(
      '正在等待处理状态更新。'
    );

    expect(streamHintSeverity('fallback_polling')).toBe('warning');
    expect(streamHintSeverity('live')).toBe('info');
  });

  it('maps source type labels', () => {
    expect(sourceTypeLabel('text')).toBe('文本');
    expect(sourceTypeLabel('url')).toBe('URL');
    expect(sourceTypeLabel('file')).toBe('文件');
    expect(sourceTypeLabel('upload')).toBe('上传文件');
  });
});
