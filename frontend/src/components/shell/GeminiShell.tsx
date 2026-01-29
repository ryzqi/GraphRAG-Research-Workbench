/**
 * Gemini 风格应用壳布局
 * 左侧可折叠 Sidebar + 中心主内容区
 */
import { useState, useCallback } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Box, IconButton, Typography, useMediaQuery, useTheme } from '@mui/material';
import { alpha } from '@mui/material/styles';
import MenuIcon from '@mui/icons-material/Menu';
import { Sidebar, SIDEBAR_WIDTH_EXPANDED, SIDEBAR_WIDTH_COLLAPSED } from './Sidebar';
import { useRecentHistory } from '../../hooks/useRecentHistory';
import { PageTransition } from '../ui/PageTransition';

export function GeminiShell() {
  const theme = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  // 侧边栏状态
  const [sidebarExpanded, setSidebarExpanded] = useState(true);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // 用于强制重置聊天页面状态（点击“新对话”时）
  const [chatResetKey, setChatResetKey] = useState(0);

  // Recent 历史 hook
  const { sessions: recentSessions, removeSession } = useRecentHistory();

  // 判断是否为聊天页面（用于调整主内容区样式）
  const isChatPage =
    location.pathname === '/' ||
    location.pathname.startsWith('/general-chat') ||
    location.pathname.startsWith('/kb-chat');

  const handleToggleSidebar = useCallback(() => {
    setSidebarExpanded((prev) => !prev);
  }, []);

  const handleMobileDrawerClose = useCallback(() => {
    setMobileDrawerOpen(false);
  }, []);

  const handleMobileDrawerOpen = useCallback(() => {
    setMobileDrawerOpen(true);
  }, []);

  const handleNewChat = useCallback(() => {
    // 通过更新 key 强制 remount 子路由，避免在同一路由下“新对话”无效果（状态不重置）
    setChatResetKey((prev) => prev + 1);

    navigate('/');
    if (isMobile) {
      setMobileDrawerOpen(false);
    }
  }, [navigate, isMobile]);

  return (
    <Box
      sx={{
        display: 'flex',
        minHeight: '100vh',
        bgcolor: 'background.default',
      }}
    >
      {/* Skip Link（可访问性） */}
      <Box
        component="a"
        href="#main-content"
        sx={{
          position: 'absolute',
          left: -9999,
          '&:focus': {
            left: 16,
            top: 16,
            zIndex: 9999,
            p: 2,
            bgcolor: 'primary.main',
            color: 'white',
            borderRadius: 3,
            textDecoration: 'none',
          },
        }}
      >
        跳到主要内容
      </Box>

      {/* 侧边栏 */}
      <Sidebar
        expanded={sidebarExpanded}
        onToggle={handleToggleSidebar}
        mobileOpen={mobileDrawerOpen}
        onMobileClose={handleMobileDrawerClose}
        recentSessions={recentSessions}
        onNewChat={handleNewChat}
        onRemoveSession={removeSession}
      />

      {/* 主内容区 */}
      <Box
        component="main"
        id="main-content"
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          position: 'relative',
          // 聊天页的“Gemini/Google”氛围光晕（轻量渐变，不影响可读性）。
          backgroundImage: isChatPage
            ? (t) =>
                t.palette.mode === 'light'
                  ? `radial-gradient(1200px 520px at 15% -10%, ${alpha(t.palette.primary.main, 0.14)} 0%, rgba(0,0,0,0) 65%),
                     radial-gradient(1000px 420px at 90% 0%, ${alpha(t.palette.success.main, 0.12)} 0%, rgba(0,0,0,0) 60%)`
                  : `radial-gradient(1200px 520px at 15% -10%, ${alpha(t.palette.primary.main, 0.10)} 0%, rgba(0,0,0,0) 65%),
                     radial-gradient(1000px 420px at 90% 0%, ${alpha(t.palette.success.main, 0.08)} 0%, rgba(0,0,0,0) 60%)`
            : undefined,
          backgroundRepeat: 'no-repeat',
          // 聊天页面全宽，其他页面限制最大宽度
          maxWidth: isChatPage
            ? '100%'
            : {
                xs: '100%',
                lg: `calc(100% - ${sidebarExpanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED}px)`,
              },
        }}
      >
        {/* 移动端顶部栏 */}
        {isMobile && (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              p: 1.5,
              borderBottom: 1,
              borderColor: 'divider',
              bgcolor: alpha(theme.palette.background.paper, 0.85),
              backdropFilter: 'blur(16px)',
              WebkitBackdropFilter: 'blur(16px)',
              position: 'sticky',
              top: 0,
              zIndex: theme.zIndex.appBar,
            }}
          >
            <IconButton onClick={handleMobileDrawerOpen} edge="start" aria-label="打开导航菜单">
              <MenuIcon />
            </IconButton>
            <Typography variant="subtitle1" fontWeight={600} sx={{ ml: 0.5 }}>
              知识代理
            </Typography>
          </Box>
        )}

        {/* 页面内容 */}
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            px: isChatPage ? 0 : { xs: 2, sm: 3, md: 4 },
            py: isChatPage ? 0 : 3,
            maxWidth: isChatPage ? '100%' : 1200,
            mx: isChatPage ? 0 : 'auto',
            width: '100%',
          }}
        >
          <PageTransition key={`${location.pathname}:${chatResetKey}`}>
            <Outlet />
          </PageTransition>
        </Box>
      </Box>
    </Box>
  );
}
