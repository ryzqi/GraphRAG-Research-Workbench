/**
 * 状态徽章组件
 * 用于显示任务运行状态
 */
import { Chip, type ChipProps } from '@mui/material';

type StatusType = 'running' | 'queued' | 'succeeded' | 'failed' | 'canceled' | 'pending';

interface StatusBadgeProps {
  status: StatusType;
  /** 可选：覆盖默认文案（默认使用内置映射） */
  label?: string;
  size?: ChipProps['size'];
}

const statusConfig: Record<StatusType, { label: string; color: ChipProps['color']; variant?: ChipProps['variant'] }> = {
  running: { label: '运行中...', color: 'warning' },
  queued: { label: '排队中...', color: 'default' },
  succeeded: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
  canceled: { label: '已取消', color: 'default' },
  pending: { label: '等待中', color: 'default' },
};

export function StatusBadge({ status, label, size = 'small' }: StatusBadgeProps) {
  const config = statusConfig[status] || { label: status, color: 'default' as const };

  return (
    <Chip
      label={label ?? config.label}
      color={config.color}
      size={size}
      variant="filled"
    />
  );
}
