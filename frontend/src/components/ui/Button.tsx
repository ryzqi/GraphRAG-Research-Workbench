/**
 * MD3 统一按钮组件
 * 封装 MUI Button，添加 loading 状态和微交互
 */
import {
  Button as MuiButton,
  type ButtonProps as MuiButtonProps,
  CircularProgress,
} from '@mui/material';

interface ButtonProps extends MuiButtonProps {
  /** 加载状态 */
  loading?: boolean;
}

export function Button({
  loading,
  disabled,
  children,
  startIcon,
  sx,
  ...props
}: ButtonProps) {
  return (
    <MuiButton
      disabled={disabled || loading}
      startIcon={
        loading ? <CircularProgress size={18} color="inherit" /> : startIcon
      }
      sx={{
        // 按压时的微交互由主题层统一处理
        // 这里可以添加额外的自定义样式
        ...sx,
      }}
      {...props}
    >
      {children}
    </MuiButton>
  );
}
