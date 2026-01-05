/**
 * 统一按钮组件
 * 封装 MUI Button，添加 loading 状态
 */
import {
  Button as MuiButton,
  type ButtonProps as MuiButtonProps,
  CircularProgress,
} from '@mui/material';

interface ButtonProps extends MuiButtonProps {
  loading?: boolean;
}

export function Button({ loading, disabled, children, startIcon, ...props }: ButtonProps) {
  return (
    <MuiButton
      disabled={disabled || loading}
      startIcon={
        loading ? <CircularProgress size={16} color="inherit" /> : startIcon
      }
      {...props}
    >
      {children}
    </MuiButton>
  );
}
