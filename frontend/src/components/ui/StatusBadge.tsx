/**
 * 状态徽章组件
 * 用于显示任务运行状态
 */
import { alpha } from '@mui/material/styles';
import { Chip, type ChipProps } from '@mui/material';

type StatusType = 'running' | 'queued' | 'succeeded' | 'failed' | 'canceled' | 'pending';

interface StatusBadgeProps {
  status: StatusType;
  /** 可选：覆盖默认文案（默认使用内置映射） */
  label?: string;
  size?: ChipProps['size'];
}

const statusConfig: Record<
  StatusType,
  { label: string; color: string; background: string; border: string }
> = {
  running: {
    label: '运行中...',
    color: '#fbbf24',
    background: 'linear-gradient(180deg, rgba(251,191,36,0.22) 0%, rgba(251,191,36,0.08) 100%)',
    border: 'rgba(251,191,36,0.28)',
  },
  queued: {
    label: '排队中...',
    color: '#cbd5e1',
    background: 'linear-gradient(180deg, rgba(148,163,184,0.18) 0%, rgba(148,163,184,0.06) 100%)',
    border: 'rgba(148,163,184,0.24)',
  },
  succeeded: {
    label: '已完成',
    color: '#34d399',
    background: 'linear-gradient(180deg, rgba(52,211,153,0.2) 0%, rgba(52,211,153,0.08) 100%)',
    border: 'rgba(52,211,153,0.24)',
  },
  failed: {
    label: '失败',
    color: '#f87171',
    background: 'linear-gradient(180deg, rgba(248,113,113,0.2) 0%, rgba(248,113,113,0.08) 100%)',
    border: 'rgba(248,113,113,0.26)',
  },
  canceled: {
    label: '已取消',
    color: '#cbd5e1',
    background: 'linear-gradient(180deg, rgba(148,163,184,0.18) 0%, rgba(148,163,184,0.06) 100%)',
    border: 'rgba(148,163,184,0.24)',
  },
  pending: {
    label: '等待中',
    color: '#93c5fd',
    background: 'linear-gradient(180deg, rgba(96,165,250,0.2) 0%, rgba(96,165,250,0.08) 100%)',
    border: 'rgba(96,165,250,0.26)',
  },
};

export function StatusBadge({ status, label, size = 'small' }: StatusBadgeProps) {
  const config = statusConfig[status] || {
    label: status,
    color: '#cbd5e1',
    background: 'linear-gradient(180deg, rgba(148,163,184,0.18) 0%, rgba(148,163,184,0.06) 100%)',
    border: 'rgba(148,163,184,0.24)',
  };

  return (
    <Chip
      label={label ?? config.label}
      size={size}
      variant="outlined"
      sx={{
        color: config.color,
        borderColor: config.border,
        background: config.background,
        backdropFilter: 'blur(12px)',
        fontWeight: 700,
        letterSpacing: '0.02em',
        '& .MuiChip-label': {
          px: 1.25,
        },
        '&.MuiChip-outlined': {
          borderWidth: 1,
        },
        boxShadow: `inset 0 1px 0 ${alpha('#ffffff', 0.1)}`,
      }}
    />
  );
}
