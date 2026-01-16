/**
 * 卡片组件
 * 封装 MUI Card，提供统一样式
 */
import {
  Card as MuiCard,
  CardContent,
  CardActions,
  CardHeader,
  type CardProps as MuiCardProps,
  type SxProps,
  type Theme,
} from '@mui/material';
import { mergeSx } from '../../utils/sx';

interface CardProps extends MuiCardProps {
  title?: string;
  subheader?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  contentSx?: SxProps<Theme>;
  noPadding?: boolean;
}

export function Card({
  title,
  subheader,
  action,
  children,
  footer,
  contentSx,
  noPadding = false,
  ...props
}: CardProps) {
  return (
    <MuiCard {...props}>
      {(title || action) && (
        <CardHeader
          title={title}
          subheader={subheader}
          action={action}
          titleTypographyProps={{ variant: 'h6' }}
          subheaderTypographyProps={{ variant: 'body2' }}
        />
      )}
      <CardContent
        sx={mergeSx(
          { pt: title ? 0 : undefined, p: noPadding ? 0 : undefined },
          contentSx
        )}
      >
        {children}
      </CardContent>
      {footer && <CardActions sx={{ px: 2, pb: 2 }}>{footer}</CardActions>}
    </MuiCard>
  );
}
