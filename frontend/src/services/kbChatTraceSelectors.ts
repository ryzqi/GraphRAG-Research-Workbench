import type { PipelineTimelineEvent } from '../components/chat/PipelineProgress';

export type KbChatTraceFilterKey = 'all' | 'started' | 'completed' | 'failed';

export function selectFilteredTimeline(
  timeline: PipelineTimelineEvent[],
  filter: KbChatTraceFilterKey
): PipelineTimelineEvent[] {
  if (filter === 'all') return timeline;
  return timeline.filter((item) => item.status === filter);
}

export function selectTimelineItem(
  timeline: PipelineTimelineEvent[],
  selectedId: string | null
): PipelineTimelineEvent | null {
  if (!selectedId) return null;
  return timeline.find((item) => item.id === selectedId) ?? null;
}

