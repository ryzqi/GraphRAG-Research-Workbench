import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { useKnowledgeBase, useKnowledgeBaseIngestionState } from './queries/useKnowledgeBases';
import { useIngestionBatchLive } from './queries/useIngestionBatches';
import { getErrorMessage } from '../lib/errorHandler';
import { buildBatchSummaryMetrics, streamHintText } from '../components/ingestion';

export function useKnowledgeBaseDetailData() {
  const params = useParams<{ kbId: string }>();
  const kbId = Array.isArray(params.kbId) ? params.kbId[0] : params.kbId;

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const ingestionStateQuery = useKnowledgeBaseIngestionState(kbId ?? '');
  const liveBatchQuery = useIngestionBatchLive({ kbId: kbId ?? undefined });

  const [showSlowLoading, setShowSlowLoading] = useState(false);
  useEffect(() => {
    if (!kbQuery.isPending) {
      setShowSlowLoading(false);
      return;
    }
    const timer = setTimeout(() => {
      setShowSlowLoading(true);
    }, 8_000);
    return () => clearTimeout(timer);
  }, [kbQuery.isPending]);

  const kb = kbQuery.data ?? null;
  const activeBatch = liveBatchQuery.data ?? null;
  const batchRunning = activeBatch?.status === 'processing';

  const browseLocked =
    ingestionStateQuery.isPending ||
    Boolean(ingestionStateQuery.error) ||
    Boolean(ingestionStateQuery.data?.has_active_batch) ||
    Boolean(batchRunning);

  const browseLockMessage = useMemo(() => {
    if (ingestionStateQuery.error) {
      return '无法确认文档处理状态，已暂时禁用分块浏览。';
    }
    if (!ingestionStateQuery.data) {
      return '正在同步文档处理状态，请稍后再浏览分块。';
    }

    if (activeBatch && activeBatch.status === 'processing') {
      const activeDocs = activeBatch.docs.filter((doc) => doc.status === 'processing').length;
      if (activeDocs > 0) {
        return `当前批次仍有 ${activeDocs} 个文档处理中，暂不可浏览分块。`;
      }
      return '当前导入批次仍在处理中，暂不可浏览分块。';
    }

    if (!ingestionStateQuery.data.has_active_batch) {
      return null;
    }

    return '当前知识库文档仍在处理中，待全部完成后再浏览分块。';
  }, [activeBatch, ingestionStateQuery.data, ingestionStateQuery.error]);

  const progressError = liveBatchQuery.error ? getErrorMessage(liveBatchQuery.error) : null;
  const summaryMetrics = activeBatch ? buildBatchSummaryMetrics(activeBatch) : null;
  const liveStreamHint = streamHintText({
    enabled: Boolean(activeBatch),
    streamStatus: liveBatchQuery.streamStatus,
    fallbackIntervalMs: liveBatchQuery.fallbackIntervalMs,
  });

  return {
    kbId,
    kbQuery,
    kb,
    showSlowLoading,
    activeBatch,
    browseLocked,
    browseLockMessage,
    progressError,
    summaryMetrics,
    liveStreamHint,
    ingestionStateQuery,
    liveBatchQuery,
  };
}
