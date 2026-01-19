/**
 * MD3 骨架屏组件
 * 替代 "加载中..." 文字，提供更好的加载体验
 */
import { Skeleton as MuiSkeleton, Box, type SxProps, type Theme } from '@mui/material';

// ============================================================================
// 卡片骨架屏
// ============================================================================

interface CardSkeletonProps {
  /** 是否显示头部区域 */
  hasHeader?: boolean;
  /** 是否显示操作区域 */
  hasActions?: boolean;
  /** 内容行数 */
  lines?: number;
  /** 自定义样式 */
  sx?: SxProps<Theme>;
}

export function CardSkeleton({
  hasHeader = true,
  hasActions = false,
  lines = 3,
  sx,
}: CardSkeletonProps) {
  return (
    <Box
      sx={{
        p: 2,
        borderRadius: 4,
        bgcolor: 'background.paper',
        ...sx,
      }}
    >
      {hasHeader && (
        <Box sx={{ mb: 2 }}>
          <MuiSkeleton
            variant="text"
            width="60%"
            height={28}
            sx={{ borderRadius: 1 }}
          />
          <MuiSkeleton
            variant="text"
            width="40%"
            height={20}
            sx={{ borderRadius: 1 }}
          />
        </Box>
      )}

      <Box sx={{ mb: hasActions ? 2 : 0 }}>
        {Array.from({ length: lines }).map((_, i) => (
          <MuiSkeleton
            key={i}
            variant="text"
            width={i === lines - 1 ? '80%' : '100%'}
            height={20}
            sx={{ borderRadius: 1, mb: 0.5 }}
          />
        ))}
      </Box>

      {hasActions && (
        <Box sx={{ display: 'flex', gap: 1, pt: 1 }}>
          <MuiSkeleton
            variant="rounded"
            width={80}
            height={36}
            sx={{ borderRadius: 5 }}
          />
          <MuiSkeleton
            variant="rounded"
            width={80}
            height={36}
            sx={{ borderRadius: 5 }}
          />
        </Box>
      )}
    </Box>
  );
}

// ============================================================================
// 列表骨架屏
// ============================================================================

interface ListSkeletonProps {
  /** 列表项数量 */
  count?: number;
  /** 是否显示头像 */
  hasAvatar?: boolean;
  /** 自定义样式 */
  sx?: SxProps<Theme>;
}

export function ListSkeleton({
  count = 5,
  hasAvatar = false,
  sx,
}: ListSkeletonProps) {
  return (
    <Box sx={sx}>
      {Array.from({ length: count }).map((_, i) => (
        <Box
          key={i}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            py: 1.5,
            borderBottom: i < count - 1 ? 1 : 0,
            borderColor: 'divider',
          }}
        >
          {hasAvatar && (
            <MuiSkeleton
              variant="circular"
              width={40}
              height={40}
            />
          )}
          <Box sx={{ flex: 1 }}>
            <MuiSkeleton
              variant="text"
              width="70%"
              height={24}
              sx={{ borderRadius: 1 }}
            />
            <MuiSkeleton
              variant="text"
              width="50%"
              height={18}
              sx={{ borderRadius: 1 }}
            />
          </Box>
        </Box>
      ))}
    </Box>
  );
}

// ============================================================================
// 卡片网格骨架屏
// ============================================================================

interface CardGridSkeletonProps {
  /** 卡片数量 */
  count?: number;
  /** Grid 列数配置 */
  columns?: {
    xs?: number;
    sm?: number;
    md?: number;
  };
  /** 自定义样式 */
  sx?: SxProps<Theme>;
}

export function CardGridSkeleton({
  count = 6,
  columns = { xs: 1, sm: 2, md: 3 },
  sx,
}: CardGridSkeletonProps) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: {
          xs: `repeat(${columns.xs ?? 1}, 1fr)`,
          sm: `repeat(${columns.sm ?? 2}, 1fr)`,
          md: `repeat(${columns.md ?? 3}, 1fr)`,
        },
        gap: 3,
        ...sx,
      }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <CardSkeleton key={i} hasActions />
      ))}
    </Box>
  );
}

// ============================================================================
// 文本块骨架屏
// ============================================================================

interface TextSkeletonProps {
  /** 行数 */
  lines?: number;
  /** 自定义样式 */
  sx?: SxProps<Theme>;
}

export function TextSkeleton({ lines = 4, sx }: TextSkeletonProps) {
  return (
    <Box sx={sx}>
      {Array.from({ length: lines }).map((_, i) => (
        <MuiSkeleton
          key={i}
          variant="text"
          width={i === lines - 1 ? '60%' : '100%'}
          height={20}
          sx={{ borderRadius: 1, mb: 0.5 }}
        />
      ))}
    </Box>
  );
}
