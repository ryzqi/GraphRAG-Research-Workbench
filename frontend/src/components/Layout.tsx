/**
 * MD3 主布局组件
 * 包含页面转场动画
 */
import { Outlet, useLocation } from 'react-router-dom';
import { Box, Container } from '@mui/material';
import { Nav } from './Nav';
import { PageTransition } from './ui/PageTransition';

export function Layout() {
  const location = useLocation();
  const isGeneralChat =
    location.pathname === '/' || location.pathname.startsWith('/general-chat');

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
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

      <Nav />

      <Container
        id="main-content"
        component="main"
        maxWidth={isGeneralChat ? false : 'lg'}
        disableGutters={isGeneralChat}
        sx={isGeneralChat ? { py: 0 } : { py: 3 }}
      >
        <PageTransition key={location.pathname}>
          <Outlet />
        </PageTransition>
      </Container>
    </Box>
  );
}
