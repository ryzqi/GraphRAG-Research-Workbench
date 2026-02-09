'use client';

/**
 * Gemini 风格应用壳布局
 * 左侧可折叠 Sidebar + 中心主内容区
 */
import { useState, useCallback, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useRouter } from 'next/navigation';
import { Box, IconButton, Typography, useMediaQuery, useTheme } from '@mui/material';
import { alpha } from '@mui/material/styles';
import MenuIcon from '@mui/icons-material/Menu';
import type { SidebarProps } from './Sidebar';
import { SIDEBAR_WIDTH_EXPANDED, SIDEBAR_WIDTH_COLLAPSED } from './constants';
import { PageTransition } from '../ui/PageTransition';

const Sidebar = dynamic<SidebarProps>(
  () => import('./Sidebar').then((mod) => mod.Sidebar),
  {
    ssr: false,
    loading: () => (
      <Box
        sx={{
          display: { xs: 'none', md: 'block' },
          width: SIDEBAR_WIDTH_EXPANDED,
          flexShrink: 0,
        }}
      />
    ),
  }
);

interface GeminiShellProps {
  children?: ReactNode;
}

export function GeminiShell({ children }: GeminiShellProps) {
  const theme = useTheme();
  const pathname = usePathname();
  const router = useRouter();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  const [sidebarExpanded, setSidebarExpanded] = useState(true);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [chatResetKey, setChatResetKey] = useState(0);

  const isChatPage =
    pathname === '/' ||
    pathname.startsWith('/general-chat') ||
    pathname.startsWith('/kb-chat');

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
    setChatResetKey((prev) => prev + 1);
    router.push('/general-chat');
    if (isMobile) {
      setMobileDrawerOpen(false);
    }
  }, [router, isMobile]);

  return (
    <Box
      sx={{
        display: 'flex',
        minHeight: '100vh',
        bgcolor: 'background.default',
      }}
    >
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

      <Sidebar
        expanded={sidebarExpanded}
        onToggle={handleToggleSidebar}
        mobileOpen={mobileDrawerOpen}
        onMobileClose={handleMobileDrawerClose}
        onNewChat={handleNewChat}
      />

      <Box
        component="main"
        id="main-content"
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          position: 'relative',
          backgroundImage: isChatPage
            ? (t) =>
                t.palette.mode === 'light'
                  ? `radial-gradient(1200px 520px at 15% -10%, ${alpha(t.palette.primary.main, 0.14)} 0%, rgba(0,0,0,0) 65%),
                     radial-gradient(1000px 420px at 90% 0%, ${alpha(t.palette.success.main, 0.12)} 0%, rgba(0,0,0,0) 60%)`
                  : `radial-gradient(1200px 520px at 15% -10%, ${alpha(t.palette.primary.main, 0.10)} 0%, rgba(0,0,0,0) 65%),
                     radial-gradient(1000px 420px at 90% 0%, ${alpha(t.palette.success.main, 0.08)} 0%, rgba(0,0,0,0) 60%)`
            : undefined,
          backgroundRepeat: 'no-repeat',
          maxWidth: isChatPage
            ? '100%'
            : {
                xs: '100%',
                lg: `calc(100% - ${sidebarExpanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED}px)`,
              },
        }}
      >
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
          <PageTransition key={`${pathname}:${chatResetKey}`}>
            {children}
          </PageTransition>
        </Box>
      </Box>
    </Box>
  );
}

