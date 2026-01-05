/**
 * 主布局组件
 */
import { Outlet } from 'react-router-dom';
import { Box, Container } from '@mui/material';
import { Nav } from './Nav';

export function Layout() {
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
            borderRadius: 1,
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
        maxWidth="lg"
        sx={{ py: 3 }}
      >
        <Outlet />
      </Container>
    </Box>
  );
}
