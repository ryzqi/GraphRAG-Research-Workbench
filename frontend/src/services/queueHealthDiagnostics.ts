export interface QueueStateSnapshot {
  consumer_count: number;
  ready_messages: number;
  required: boolean;
  healthy: boolean;
}

export interface QueueHealthSnapshot {
  workers_online: boolean;
  queues: Record<string, QueueStateSnapshot>;
  stuck_summary: {
    bootstrap_queued_jobs: number;
    processing_docs_over_sla: number;
    research_queued_sessions: number;
  };
  timestamp: string;
}

interface BuildQueueHealthHintOptions {
  snapshot: QueueHealthSnapshot | null | undefined;
  waitingBootstrapBatch: boolean;
  batchProcessing: boolean;
  waitingResearchSession?: boolean;
}

function formatQueueIssue(queueName: string, state: QueueStateSnapshot): string {
  return `${queueName} 队列暂无消费者（积压 ${state.ready_messages} 条）`;
}

export function buildQueueHealthHint(options: BuildQueueHealthHintOptions): string | null {
  const { snapshot, waitingBootstrapBatch, batchProcessing, waitingResearchSession = false } = options;
  if (!snapshot) {
    return null;
  }

  if (!snapshot.workers_online) {
    return 'Celery worker 全部离线，请检查 default / dispatch / ingestion / research worker 进程。';
  }

  const defaultQueue = snapshot.queues.default;
  if (waitingBootstrapBatch && defaultQueue && !defaultQueue.healthy) {
    return `${formatQueueIssue('default', defaultQueue)}，bootstrap 任务无法从 queued 进入运行。`;
  }

  const ingestionQueue = snapshot.queues.ingestion;
  if (batchProcessing && ingestionQueue && !ingestionQueue.healthy) {
    return `${formatQueueIssue('ingestion', ingestionQueue)}，文档任务可能长期停留在 processing。`;
  }

  const dispatchQueue = snapshot.queues.dispatch;
  if (waitingResearchSession && dispatchQueue && !dispatchQueue.healthy) {
    return `${formatQueueIssue('dispatch', dispatchQueue)}，深度研究任务暂时无法写入 research 队列。`;
  }

  const researchQueue = snapshot.queues.research;
  if (waitingResearchSession && researchQueue && !researchQueue.healthy) {
    return `${formatQueueIssue('research', researchQueue)}，深度研究任务无法从 queued 进入运行。`;
  }

  if (waitingBootstrapBatch && snapshot.stuck_summary.bootstrap_queued_jobs > 0) {
    return `检测到 ${snapshot.stuck_summary.bootstrap_queued_jobs} 个 bootstrap 任务超过阈值仍未调度。`;
  }

  if (batchProcessing && snapshot.stuck_summary.processing_docs_over_sla > 0) {
    return `检测到 ${snapshot.stuck_summary.processing_docs_over_sla} 个文档超过阈值仍在 processing。`;
  }

  if (waitingResearchSession && snapshot.stuck_summary.research_queued_sessions > 0) {
    return `检测到 ${snapshot.stuck_summary.research_queued_sessions} 个深度研究会话超过阈值仍未调度。`;
  }

  return null;
}
