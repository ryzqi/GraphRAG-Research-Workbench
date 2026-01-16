/**
 * 错误提示组件
 * 封装 MUI Alert，提供统一的错误展示
 */
import { Alert, type AlertProps, Collapse } from '@mui/material';
import { mergeSx } from '../../utils/sx';

interface ErrorAlertProps extends Omit<AlertProps, 'severity'> {
  /** 错误信息，为 null 时不显示 */
  error: string | null;
  /** 严重程度，默认 error */
  severity?: 'error' | 'warning' | 'info';
}

export function ErrorAlert({
  error,
  severity = 'error',
  sx,
  onClose,
  ...props
}: ErrorAlertProps) {
  return (
    <Collapse in={!!error}>
      <Alert
        severity={severity}
        onClose={onClose}
        sx={mergeSx({ mt: 2 }, sx)}
        {...props}
      >
        {error}
      </Alert>
    </Collapse>
  );
}
