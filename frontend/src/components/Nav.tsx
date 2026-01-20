/**
 * MD3 导航栏组件
 * 支持滚动时背景填充效果
 */
import { NavLink, useLocation } from 'react-router-dom';
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
import ChatIcon from '@mui/icons-material/Chat';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import SearchIcon from '@mui/icons-material/Search';
import StorageIcon from '@mui/icons-material/Storage';
import ExtensionIcon from '@mui/icons-material/Extension';
import AssessmentIcon from '@mui/icons-material/Assessment';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import { useThemeMode } from '../theme/ThemeProvider';
import { md3Easing, md3Duration } from '../utils/motion';

// 路由预加载配置
const routePreloaders: Record<string, () => Promise<unknown>> = {
  '/': () => import('../pages/GeneralChatPage'),
  '/kb-chat': () => import('../pages/KbChatPage'),
  '/general-chat': () => import('../pages/GeneralChatPage'),
  '/knowledge-bases': () => import('../pages/KnowledgeBasesPage'),
  '/research': () => import('../pages/ResearchPage'),
  '/extensions': () => import('../pages/ExtensionsPage'),
  '/evaluations': () => import('../pages/EvaluationsPage'),
};

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

function preloadRoute(path: string) {
  if (!shouldPreloadRoute()) return;
  const preload = routePreloaders[path];
  if (preload) void preload();
}

const navItems = [
  { path: '/', label: '普通代理', icon: SmartToyIcon, end: true },
  { path: '/kb-chat', label: '知识库问答', icon: ChatIcon },
  { path: '/knowledge-bases', label: '知识库管理', icon: StorageIcon },
  { path: '/research', label: '深度研究', icon: SearchIcon },
  { path: '/extensions', label: 'MCP扩展', icon: ExtensionIcon },
  { path: '/evaluations', label: '对比评测', icon: AssessmentIcon },
];

export function Nav() {
  const location = useLocation();
  const { resolvedMode, toggleMode } = useThemeMode();

  // 滚动检测 - 用于 On-scroll 背景填充效果
  const scrolled = useScrollTrigger({
    disableHysteresis: true,
    threshold: 0,
  });

  return (
    <AppBar
      position="sticky"
      color="inherit"
      sx={{
        // MD3 On-scroll 效果：滚动时背景填充
        bgcolor: scrolled
          ? (theme) =>
              theme.palette.mode === 'light'
                ? '#e9e8ec' // surfaceContainerHigh
                : '#292a2d'
          : 'transparent',
        boxShadow: scrolled ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
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
          {navItems.map(({ path, label, icon: Icon, end }) => {
            const isActive = end
              ? location.pathname === path
              : location.pathname.startsWith(path);

            return (
              <Button
                key={path}
                component={NavLink}
                to={path}
                startIcon={<Icon fontSize="small" />}
                size="small"
                onMouseEnter={() => preloadRoute(path)}
                onFocus={() => preloadRoute(path)}
                onTouchStart={() => preloadRoute(path)}
                sx={{
                  color: isActive ? 'primary.main' : 'text.secondary',
                  bgcolor: isActive
                    ? (theme) =>
                        theme.palette.mode === 'light'
                          ? 'rgba(26, 115, 232, 0.12)'
                          : 'rgba(201, 222, 255, 0.12)'
                    : 'transparent',
                  fontWeight: isActive ? 500 : 400,
                  whiteSpace: 'nowrap',
                  px: 2,
                  borderRadius: 5, // 全圆角 pill
                  '&:hover': {
                    bgcolor: isActive
                      ? (theme) =>
                          theme.palette.mode === 'light'
                            ? 'rgba(26, 115, 232, 0.16)'
                            : 'rgba(201, 222, 255, 0.16)'
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
