/**
 * MD3 卡片组件
 * 支持 filled/outlined/elevation 三种变体
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

/** Card 变体类型 */
export type CardVariant = 'filled' | 'outlined' | 'elevation';

interface CardProps extends Omit<MuiCardProps, 'variant'> {
  /** MD3 Card 变体 */
  variant?: CardVariant;
  title?: string;
  subheader?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  contentSx?: SxProps<Theme>;
  noPadding?: boolean;
  /** 禁用 hover 效果 */
  disableHover?: boolean;
}

/** 根据变体获取样式 */
function getVariantStyles(
  variant: CardVariant,
  disableHover: boolean
): SxProps<Theme> {
  const baseTransition = 'background-color 300ms cubic-bezier(0.2, 0, 0, 1), box-shadow 300ms cubic-bezier(0.2, 0, 0, 1)';

  switch (variant) {
    case 'filled':
      return {
        bgcolor: 'background.paper',
        border: 'none',
        boxShadow: 'none',
        transition: baseTransition,
        ...(!disableHover && {
          '&:hover': {
            bgcolor: 'action.hover',
          },
        }),
      };

    case 'outlined':
      return {
        bgcolor: 'transparent',
        border: 1,
        borderColor: 'divider',
        boxShadow: 'none',
        transition: baseTransition,
        ...(!disableHover && {
          '&:hover': {
            borderColor: 'primary.main',
            bgcolor: 'action.selected',
          },
        }),
      };

    case 'elevation':
      return {
        bgcolor: 'background.paper',
        border: 'none',
        boxShadow: 1,
        transition: baseTransition,
        ...(!disableHover && {
          '&:hover': {
            boxShadow: 3,
          },
        }),
      };

    default:
      return {};
  }
}

export function Card({
  variant = 'filled',
  title,
  subheader,
  action,
  children,
  footer,
  contentSx,
  noPadding = false,
  disableHover = false,
  sx,
  ...props
}: CardProps) {
  const variantStyles = getVariantStyles(variant, disableHover);

  return (
    <MuiCard
      sx={mergeSx(variantStyles, sx)}
      {...props}
    >
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
