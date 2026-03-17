import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  Collapse,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import type { ChatRunStateEvent, ChatTraceExecution, KbGraphSchema } from '../../services/chats';
import { selectKbChatFlowDetailItems } from '../../services/kbChatFlowSelectors';
import {
  buildTraceExecutionTimeline,
  buildTraceStageSummaries,
  type TraceStageStatus,
} from '../../services/kbChatTraceNodes';
import { resolveKbNodeTheme } from '../../services/kbNodeCatalog';
import { KbChatFlowNodeDetailSections } from './KbChatFlowNodeDetailSections';

interface KbChatFlowPanelProps {
  schema: KbGraphSchema | null;
  runState?: ChatRunStateEvent;
  traceExecutions?: ChatTraceExecution[];
  traceWarnings?: string[];
  defaultExpandedExecutionId?: string | null;
}

function statusLabel(status: TraceStageStatus | 'started'): string {
  switch (status) {
    case 'started':
    case 'running':
      return '进行中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'waiting_user':
      return '待补充';
    case 'skipped':
      return '已跳过';
    default:
      return '待执行';
  }
}

function statusChipColor(
  status: TraceStageStatus | 'started'
): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' {
  switch (status) {
    case 'started':
    case 'running':
      return 'info';
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'waiting_user':
      return 'warning';
    default:
      return 'default';
  }
}

function statusBorderColor(status: TraceStageStatus | 'started'): string {
  switch (status) {
    case 'started':
    case 'running':
      return 'rgba(56, 189, 248, 0.55)';
    case 'completed':
      return 'rgba(74, 222, 128, 0.52)';
    case 'failed':
      return 'rgba(248, 113, 113, 0.55)';
    case 'waiting_user':
      return 'rgba(251, 191, 36, 0.56)';
    default:
      return 'rgba(100, 116, 139, 0.34)';
  }
}

function formatTime(ts?: string | null): string | null {
  if (!ts) {
    return null;
  }
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    return ts;
  }
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function extractTraceCommandGoto(snapshot: Record<string, unknown>): string | null {
  const command = asRecord(snapshot.__trace_command__) ?? {};
  return typeof command.goto === 'string' ? command.goto : null;
}

function NodeBadge({ nodeId, schema }: { nodeId: string; schema: KbGraphSchema | null }) {
  const theme = resolveKbNodeTheme(nodeId, schema);
  const Icon = theme.icon;
  return (
    <Box
      component='span'
      aria-label={theme.label}
      sx={(muiTheme) => ({
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 22,
        height: 22,
        borderRadius: 999,
        color: theme.color,
        border: `1px solid ${alpha(theme.color, muiTheme.palette.mode === 'light' ? 0.35 : 0.58)}`,
        backgroundImage: `linear-gradient(135deg, ${alpha(theme.color, muiTheme.palette.mode === 'light' ? 0.16 : 0.36)}, ${alpha(theme.color, muiTheme.palette.mode === 'light' ? 0.08 : 0.18)})`,
      })}
    >
      <Icon sx={{ fontSize: 14 }} />
    </Box>
  );
}

export function KbChatFlowPanel({
  schema,
  runState,
  traceExecutions,
  traceWarnings,
  defaultExpandedExecutionId,
}: KbChatFlowPanelProps) {
  const [expandedExecutionId, setExpandedExecutionId] = useState<string | null>(
    defaultExpandedExecutionId ?? null
  );

  useEffect(() => {
    setExpandedExecutionId(defaultExpandedExecutionId ?? null);
  }, [defaultExpandedExecutionId]);

  const executionTimeline = useMemo(
    () => buildTraceExecutionTimeline({ schema, runState, traceExecutions }),
    [schema, runState, traceExecutions]
  );
  const stageSummaries = useMemo(
    () => buildTraceStageSummaries({ schema, runState, traceExecutions }),
    [schema, runState, traceExecutions]
  );

  return (
    <Paper
      variant='outlined'
      sx={{
        p: 1.5,
        borderRadius: 3,
        height: '100%',
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        borderColor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.primary.main, 0.22)
            : alpha(theme.palette.primary.light, 0.3),
        bgcolor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.background.paper, 0.88)
            : alpha(theme.palette.background.paper, 0.44),
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
      }}
    >
      <Stack spacing={1.25} sx={{ minHeight: 0, flex: 1 }}>
        <Box>
          <Typography variant='subtitle1' fontWeight={700}>
            节点执行过程
          </Typography>
        </Box>

        {runState?.progress && (
          <Stack spacing={0.6}>
            <Stack direction='row' justifyContent='space-between'>
              <Typography variant='caption' color='text.secondary'>
                整体进度
              </Typography>
              <Typography variant='caption' color='text.secondary'>
                {runState.progress.completed}/{runState.progress.total} · {runState.progress.percent}%
              </Typography>
            </Stack>
            <LinearProgress
              variant='determinate'
              value={Math.max(0, Math.min(100, runState.progress.percent))}
              sx={{ height: 6, borderRadius: 999 }}
            />
          </Stack>
        )}

        <Stack direction='row' spacing={0.8} useFlexGap flexWrap='wrap'>
          {stageSummaries.map((stage) => (
            <Paper
              key={stage.id}
              variant='outlined'
              sx={{
                px: 1,
                py: 0.8,
                borderRadius: 2,
                minWidth: 132,
                flex: '1 1 160px',
                borderColor: statusBorderColor(stage.status),
                bgcolor: stage.isActive
                  ? (theme) => alpha(theme.palette.primary.main, 0.05)
                  : (theme) => alpha(theme.palette.background.default, 0.32),
              }}
            >
              <Stack spacing={0.5}>
                <Stack direction='row' justifyContent='space-between' alignItems='center'>
                  <Typography variant='caption' fontWeight={700}>
                    {stage.title}
                  </Typography>
                  <Chip
                    size='small'
                    label={statusLabel(stage.status)}
                    color={statusChipColor(stage.status)}
                    sx={{ height: 20 }}
                  />
                </Stack>
                <Typography variant='caption' color='text.secondary'>
                  {stage.currentNodeLabel ? `当前节点：${stage.currentNodeLabel}` : stage.subtitle}
                </Typography>
                <Typography variant='caption' color='text.secondary'>
                  执行实例 {stage.executionCount}
                </Typography>
              </Stack>
            </Paper>
          ))}
        </Stack>

        {traceWarnings && traceWarnings.length > 0 && (
          <Alert severity='warning' sx={{ py: 0.5 }}>
            <Stack spacing={0.35}>
              {traceWarnings.slice(-3).map((warning) => (
                <Typography key={warning} variant='caption'>
                  {warning}
                </Typography>
              ))}
            </Stack>
          </Alert>
        )}

        <Stack
          spacing={1}
          sx={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            pr: 0.25,
          }}
        >
          {executionTimeline.length === 0 ? (
            <Paper variant='outlined' sx={{ p: 1.2, borderRadius: 2 }}>
              <Typography variant='body2' color='text.secondary'>
                等待节点开始执行
              </Typography>
            </Paper>
          ) : (
            executionTimeline.map((execution, index) => {
              const isExpanded = expandedExecutionId === execution.execution_id;
              const inputItems = selectKbChatFlowDetailItems({
                nodeId: execution.node_name,
                section: 'input',
                items: execution.input_items,
                event: null,
              });
              const outputItems = selectKbChatFlowDetailItems({
                nodeId: execution.node_name,
                section: 'output',
                items: execution.output_items,
                event: null,
              });
              const startedAt = formatTime(execution.started_at);
              const endedAt = formatTime(execution.ended_at ?? execution.updated_at);
              return (
                <Paper
                  key={execution.execution_id}
                  variant='outlined'
                  sx={{
                    p: 1.1,
                    borderRadius: 2,
                    borderColor: statusBorderColor(execution.status),
                    bgcolor: execution.isActive
                      ? (theme) => alpha(theme.palette.primary.main, 0.06)
                      : (theme) => alpha(theme.palette.background.default, 0.26),
                  }}
                >
                  <Stack spacing={0.9}>
                    <Stack direction='row' spacing={1} alignItems='flex-start'>
                      <Typography variant='caption' color='text.secondary' sx={{ minWidth: 18, pt: 0.35 }}>
                        {index + 1}
                      </Typography>
                      <Stack spacing={0.8} sx={{ minWidth: 0, flex: 1 }}>
                        <Stack direction='row' justifyContent='space-between' alignItems='center' spacing={1}>
                          <Stack direction='row' spacing={0.8} alignItems='center' sx={{ minWidth: 0, flex: 1 }}>
                            <NodeBadge nodeId={execution.node_name} schema={schema} />
                            <Box sx={{ minWidth: 0, flex: 1 }}>
                              <Typography variant='body2' fontWeight={700} noWrap>
                                {execution.node_label}
                              </Typography>
                              <Typography variant='caption' color='text.secondary' noWrap>
                                {execution.summaryText}
                              </Typography>
                            </Box>
                          </Stack>
                          <Stack direction='row' spacing={0.5} alignItems='center'>
                            <Chip
                              size='small'
                              label={statusLabel(execution.status)}
                              color={statusChipColor(execution.status)}
                              sx={{ height: 22 }}
                            />
                            <Tooltip title={isExpanded ? '收起详情' : '展开详情'}>
                              <IconButton
                                size='small'
                                onClick={() =>
                                  setExpandedExecutionId((current) =>
                                    current === execution.execution_id ? null : execution.execution_id
                                  )
                                }
                                sx={{
                                  transform: isExpanded ? 'rotate(180deg)' : 'none',
                                  transition: 'transform 180ms ease',
                                }}
                              >
                                <ExpandMoreIcon fontSize='small' />
                              </IconButton>
                            </Tooltip>
                          </Stack>
                        </Stack>

                        <Stack direction='row' spacing={1.2} useFlexGap flexWrap='wrap'>
                          {startedAt && (
                            <Typography variant='caption' color='text.secondary'>
                              开始 {startedAt}
                            </Typography>
                          )}
                          {endedAt && (
                            <Typography variant='caption' color='text.secondary'>
                              更新 {endedAt}
                            </Typography>
                          )}
                          {typeof execution.latency_ms === 'number' && (
                            <Typography variant='caption' color='text.secondary'>
                              耗时 {execution.latency_ms} ms
                            </Typography>
                          )}
                        </Stack>

                        <Collapse in={isExpanded} timeout='auto' unmountOnExit>
                          <Box sx={{ pt: 0.4 }}>
                            <KbChatFlowNodeDetailSections
                              inputItems={inputItems}
                              outputItems={outputItems}
                            />
                          </Box>
                        </Collapse>
                      </Stack>
                    </Stack>
                  </Stack>
                </Paper>
              );
            })
          )}
        </Stack>
      </Stack>
    </Paper>
  );
}
