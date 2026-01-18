/**
 * 导航栏组件
 * Google Material Design 风格
 */
import { NavLink, useLocation } from 'react-router-dom';
import { AppBar, Box, Button, Toolbar, Typography } from '@mui/material';
import HomeIcon from '@mui/icons-material/Home';
import ChatIcon from '@mui/icons-material/Chat';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import SearchIcon from '@mui/icons-material/Search';
import StorageIcon from '@mui/icons-material/Storage';
import ExtensionIcon from '@mui/icons-material/Extension';
import AssessmentIcon from '@mui/icons-material/Assessment';
import FeedbackIcon from '@mui/icons-material/Feedback';

// 在用户“意图明确”（hover/focus）时预加载路由 chunk，减少切换页面的等待。
// 对齐 Vercel bundle-preload。
const routePreloaders: Record<string, () => Promise<unknown>> = {
  '/': () => import('../pages/HomePage'),
  '/kb-chat': () => import('../pages/KbChatPage'),
  '/general-chat': () => import('../pages/GeneralChatPage'),
  '/research': () => import('../pages/ResearchPage'),
  '/knowledge-bases': () => import('../pages/KnowledgeBasesPage'),
  '/extensions': () => import('../pages/ExtensionsPage'),
  '/evaluations': () => import('../pages/EvaluationsPage'),
  '/feedback': () => import('../pages/FeedbackPage'),
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
  { path: '/', label: '首页', icon: HomeIcon, end: true },
  { path: '/kb-chat', label: '知识库代理', icon: ChatIcon },
  { path: '/general-chat', label: '全能代理', icon: SmartToyIcon },
  { path: '/research', label: '深度研究', icon: SearchIcon },
  { path: '/knowledge-bases', label: '知识库管理', icon: StorageIcon },
  { path: '/extensions', label: '扩展管理', icon: ExtensionIcon },
  { path: '/evaluations', label: '对比评测', icon: AssessmentIcon },
  { path: '/feedback', label: '反馈管理', icon: FeedbackIcon },
];

export function Nav() {
  const location = useLocation();

  return (
    <AppBar
      position="sticky"
      color="inherit"
      sx={{ borderBottom: 1, borderColor: 'divider' }}
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

        <Box sx={{ display: 'flex', gap: 0.5 }}>
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
                  bgcolor: isActive ? 'primary.50' : 'transparent',
                  fontWeight: isActive ? 500 : 400,
                  whiteSpace: 'nowrap',
                  px: 1.5,
                  '&:hover': {
                    bgcolor: isActive ? 'primary.100' : 'action.hover',
                  },
                }}
              >
                {label}
              </Button>
            );
          })}
        </Box>
      </Toolbar>
    </AppBar>
  );
}
