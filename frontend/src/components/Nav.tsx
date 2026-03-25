'use client';

/**
 * MD3 导航栏组件
 * 支持滚动时背景填充效果
 */
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  AppBar,
  Box,
  Button,
  Toolbar,
  Typography,
  useScrollTrigger,
  IconButton,
  Tooltip,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ChatIcon from '@mui/icons-material/Chat';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import SearchIcon from '@mui/icons-material/Search';
import StorageIcon from '@mui/icons-material/Storage';
import ExtensionIcon from '@mui/icons-material/Extension';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import { useThemeMode } from '../theme/ThemeProvider';
import { md3Easing, md3Duration } from '../utils/motion';

function shouldPreloadRoute() {
  if (typeof navigator === 'undefined') return true;
  const connection = (
    navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }
  ).connection;
  if (!connection) return true;
  if (connection.saveData) return false;
  const effectiveType = connection.effectiveType;
  return !effectiveType || (effectiveType !== 'slow-2g' && effectiveType !== '2g');
}

function preloadRoute(path: string, router: { prefetch: (href: string) => void }) {
  if (!shouldPreloadRoute()) return;
  void router.prefetch(path);
}

const navItems = [
  { href: '/', label: '普通代理', icon: SmartToyIcon, end: true },
  { href: '/kb-chat', label: '知识库问答', icon: ChatIcon },
  { href: '/knowledge-bases', label: '知识库管理', icon: StorageIcon },
  { href: '/research', label: '深度研究', icon: SearchIcon },
  { href: '/extensions', label: 'MCP扩展', icon: ExtensionIcon },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const { resolvedMode, toggleMode } = useThemeMode();

  // 监听滚动状态，用于滚动时的背景填充效果。
  const scrolled = useScrollTrigger({
    disableHysteresis: true,
    threshold: 0,
  });

  return (
    <AppBar
      position="sticky"
      color="inherit"
      sx={{
        // MD3 滚动效果：滚动时填充背景。
        bgcolor: scrolled
          ? 'background.paper'
          : 'transparent',
        boxShadow: scrolled ? 1 : 'none',
        borderBottom: scrolled ? 'none' : 1,
        borderColor: 'divider',
        transition: `background-color ${md3Duration.medium2}ms ${md3Easing.standard}, box-shadow ${md3Duration.medium2}ms ${md3Easing.standard}`,
        backdropFilter: scrolled ? 'blur(8px)' : 'none',
      }}
    >
      <Toolbar sx={{ gap: 0.5, overflowX: 'auto' }}>
        <Typography
          variant="h6"
          component="div"
          sx={{
            mr: 3,
            fontWeight: 600,
            color: 'primary.main',
            whiteSpace: 'nowrap',
          }}
        >
          知识代理
        </Typography>

        <Box sx={{ display: 'flex', gap: 0.5, flex: 1 }}>
          {navItems.map(({ href, label, icon: Icon, end }) => {
            const isActive = end
              ? pathname === href || pathname.startsWith('/general-chat')
              : pathname.startsWith(href);

            return (
              <Button
                key={href}
                component={Link}
                href={href}
                startIcon={<Icon fontSize="small" />}
                size="small"
                onMouseEnter={() => preloadRoute(href, router)}
                onFocus={() => preloadRoute(href, router)}
                onTouchStart={() => preloadRoute(href, router)}
                sx={{
                  color: isActive ? 'primary.main' : 'text.secondary',
                  bgcolor: isActive
                    ? (theme) => alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.12 : 0.2)
                    : 'transparent',
                  fontWeight: isActive ? 500 : 400,
                  whiteSpace: 'nowrap',
                  px: 2,
                  borderRadius: 5, // 全圆角 pill
                  '&:hover': {
                    bgcolor: isActive
                      ? (theme) => alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.16 : 0.24)
                      : 'action.hover',
                  },
                }}
              >
                {label}
              </Button>
            );
          })}
        </Box>

        {/* 主题切换按钮 */}
        <Tooltip title={resolvedMode === 'light' ? '切换到深色模式' : '切换到浅色模式'}>
          <IconButton
            onClick={toggleMode}
            aria-label={resolvedMode === 'light' ? '切换到深色模式' : '切换到浅色模式'}
            color="inherit"
            sx={{
              ml: 1,
              color: 'text.secondary',
            }}
          >
            {resolvedMode === 'light' ? <Brightness4Icon /> : <Brightness7Icon />}
          </IconButton>
        </Tooltip>
      </Toolbar>
    </AppBar>
  );
}


