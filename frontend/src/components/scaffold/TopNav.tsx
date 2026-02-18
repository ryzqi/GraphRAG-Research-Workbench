'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import { useThemeMode } from '@/providers/ThemeModeProvider';

const navItems = [
  { href: '/general-chat', label: 'General Chat' },
  { href: '/kb-chat', label: 'KB Chat' },
  { href: '/knowledge-bases', label: '知识库' },
  { href: '/research', label: 'Research' },
  { href: '/extensions', label: 'Extensions' },
];

function isActive(pathname: string, href: string): boolean {
  if (href === '/general-chat') {
    return pathname === '/' || pathname.startsWith('/general-chat');
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function TopNav() {
  const pathname = usePathname();
  const { resolvedMode, toggleMode } = useThemeMode();

  return (
    <AppBar position="sticky" color="transparent" elevation={0}>
      <Toolbar sx={{ borderBottom: '1px solid', borderColor: 'divider', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h6" component="span" sx={{ fontWeight: 700, mr: 1 }}>
          Next Stage 1
        </Typography>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ flex: 1 }}>
          {navItems.map((item) => (
            <Button
              key={item.href}
              component={Link}
              href={item.href}
              variant={isActive(pathname, item.href) ? 'contained' : 'text'}
              size="small"
            >
              {item.label}
            </Button>
          ))}
        </Stack>
        <Box>
          <Button onClick={toggleMode} size="small" variant="outlined">
            Theme: {resolvedMode}
          </Button>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
