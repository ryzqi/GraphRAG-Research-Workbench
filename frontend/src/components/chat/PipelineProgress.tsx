import { Alert, Box, Chip, LinearProgress, Paper, Stack, Typography } from '@mui/material';
import type { ChatRunStateEvent } from '../../services/chats';

export type PipelineStepStatus = 'started' | 'completed' | 'failed' | 'waiting_user' | 'skipped';

export interface PipelineStep {
  step_id: string;
  label: string;
  status: PipelineStepStatus;
  node?: string;
  message?: string;
  ts?: string;
  meta?: Record<string, unknown>;
}

export interface PipelineTimelineEvent {
  id: string;
  source: 'step' | 'state' | 'ui';
  step_id: string | null;
  label: string;
  node: string | null;
  status: string;
  run_status: ChatRunStateEvent['run_status'] | null;
  attempt: number | null;
  message: string | null;
  io_summary?: Record<string, unknown> | null;
  event_type?: string | null;
  ts: string;
}

interface PipelineProgressProps {
  timeline: PipelineTimelineEvent[];
  isStreaming: boolean;
  runState?: ChatRunStateEvent;
}

function statusLabel(status: string): string {
  switch (status) {
    case 'started':
      return '进行中';
    case 'completed':
      return '完成';
    case 'failed':
      return '失败';
    case 'waiting_user':
      return '等待补充';
    case 'skipped':
      return '跳过';
    case 'running':
      return '运行中';
    case 'succeeded':
      return '已完成';
    case 'canceled':
      return '已取消';
    default:
      return status;
  }
}

function statusChipColor(
  status: string
): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' {
  switch (status) {
    case 'completed':
    case 'succeeded':
      return 'success';
    case 'failed':
      return 'error';
    case 'waiting_user':
      return 'warning';
    case 'running':
    case 'started':
      return 'info';
    default:
      return 'default';
  }
}

function statusDotColor(status: string): string {
  switch (status) {
    case 'completed':
    case 'succeeded':
      return 'success.main';
    case 'failed':
      return 'error.main';
    case 'waiting_user':
      return 'warning.main';
    case 'running':
    case 'started':
      return 'info.main';
    case 'skipped':
      return 'text.disabled';
    default:
      return 'text.secondary';
  }
}

function runStatusLabel(status: ChatRunStateEvent['run_status']): string {
  switch (status) {
    case 'succeeded':
      return '已完成';
    case 'failed':
      return '失败';
    case 'canceled':
      return '已取消';
    case 'waiting_user':
      return '等待补充';
    default:
      return '运行中';
  }
}

function formatTime(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    return ts;
  }
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

function formatIoSummary(summary: Record<string, unknown> | null | undefined): string {
  if (!summary) return '';
  const entries = Object.entries(summary)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => {
      if (typeof value === 'boolean') {
        return `${key}=${value ? '是' : '否'}`;
      }
      if (typeof value === 'number') {
        return `${key}=${value}`;
      }
      if (typeof value === 'string') {
        return `${key}=${value}`;
      }
      return `${key}=${JSON.stringify(value)}`;
    })
    .slice(0, 6);
  return entries.join(' · ');
}

function asFallbackTimeline(state: ChatRunStateEvent): PipelineTimelineEvent {
  return {
    id: `state-${state.run_id}-${state.state_version ?? state.ts}`,
    source: 'state',
    step_id: state.current_step_id,
    label: state.current_step_label ?? state.current_node ?? '执行状态',
    node: state.current_node,
    status: state.current_step_status ?? state.run_status,
    run_status: state.run_status,
    attempt: state.attempt,
    message: state.message,
    ts: state.ts,
  };
}

export function PipelineProgress({ timeline, isStreaming, runState }: PipelineProgressProps) {
  const entries =
    timeline.length > 0 ? timeline : runState ? [asFallbackTimeline(runState)] : [];

  if (entries.length === 0 && !runState) {
    return null;
  }

  const progress = runState?.progress;
  const progressValue = progress?.percent ?? 0;
  const activePath = runState?.active_path ?? [];

  return (
    <Paper
      variant='outlined'
      sx={{
        p: 1.5,
        borderRadius: 2.5,
        borderColor: (theme) =>
          theme.palette.mode === 'light' ? 'rgba(71,85,105,0.24)' : 'rgba(100,116,139,0.36)',
        bgcolor: (theme) =>
          theme.palette.mode === 'light' ? 'rgba(248,250,252,0.9)' : 'rgba(15,23,42,0.6)',
      }}
    >
      <Stack spacing={1}>
        <Stack direction='row' alignItems='center' justifyContent='space-between'>
          <Box>
            <Typography variant='caption' color='text.secondary'>
              LangGraph 运行轨迹
            </Typography>
            <Typography variant='body2' fontWeight={700}>
              {entries.length} 条事件
            </Typography>
          </Box>
          {runState && (
            <Chip
              size='small'
              label={runStatusLabel(runState.run_status)}
              color={statusChipColor(runState.run_status)}
              sx={{ height: 22 }}
            />
          )}
        </Stack>

        {progress && (
          <Stack spacing={0.5}>
            <Stack direction='row' justifyContent='space-between'>
              <Typography variant='caption' color='text.secondary'>
                进度 {progress.completed}/{progress.total}
              </Typography>
              <Typography variant='caption' color='text.secondary'>
                {progressValue}%
              </Typography>
            </Stack>
            <LinearProgress
              variant='determinate'
              value={Math.max(0, Math.min(100, progressValue))}
              sx={{ height: 6, borderRadius: 999 }}
            />
          </Stack>
        )}

        {activePath.length > 0 && (
          <Stack direction='row' spacing={0.5} useFlexGap flexWrap='wrap'>
            {activePath.slice(-6).map((stepId) => (
              <Chip key={stepId} size='small' variant='outlined' label={stepId} sx={{ height: 20 }} />
            ))}
          </Stack>
        )}

        <Stack spacing={0.75} aria-live='polite'>
          {entries.map((entry, index) => {
            const isLast = index === entries.length - 1;
            const details = [
              entry.node ? `节点 ${entry.node}` : null,
              typeof entry.attempt === 'number' ? `第 ${entry.attempt} 次` : null,
              formatIoSummary(entry.io_summary),
              entry.message,
            ]
              .filter(Boolean)
              .join(' · ');

            return (
              <Stack key={entry.id || `${entry.source}-${index}`} direction='row' spacing={1}>
                <Box
                  sx={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    bgcolor: statusDotColor(entry.status),
                    mt: 0.75,
                    flexShrink: 0,
                  }}
                />
                <Stack spacing={0.25} sx={{ minWidth: 0, flex: 1 }}>
                  <Stack direction='row' spacing={0.75} alignItems='center' useFlexGap flexWrap='wrap'>
                    <Typography variant='caption' fontWeight={isLast ? 700 : 600}>
                      {entry.label}
                    </Typography>
                    <Chip
                      size='small'
                      label={statusLabel(entry.status)}
                      color={statusChipColor(entry.status)}
                      sx={{ height: 20 }}
                    />
                    <Typography variant='caption' color='text.secondary'>
                      {formatTime(entry.ts)}
                    </Typography>
                  </Stack>
                  {details && (
                    <Typography
                      variant='caption'
                      color={entry.status === 'failed' ? 'error.main' : 'text.secondary'}
                    >
                      {details}
                    </Typography>
                  )}
                </Stack>
              </Stack>
            );
          })}
        </Stack>

        {runState?.degrade_reason && runState?.last_good_answer && (
          <Alert severity='warning'>
            <Typography variant='caption' sx={{ display: 'block', mb: 0.4 }}>
              终态失败：{runState.degrade_reason}
            </Typography>
            <Typography variant='body2' sx={{ whiteSpace: 'pre-wrap' }}>
              {runState.last_good_answer}
            </Typography>
          </Alert>
        )}

        {isStreaming && (
          <Typography variant='caption' color='text.secondary'>
            状态持续更新中...
          </Typography>
        )}
      </Stack>
    </Paper>
  );
}
