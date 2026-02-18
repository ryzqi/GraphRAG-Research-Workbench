/**
 * Gemini 风格侧边栏组件
 * 支持桌面端可折叠、移动端 Drawer 模式
 */
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  Box,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
  Typography,
  Divider,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import MenuIcon from '@mui/icons-material/Menu';
import MenuOpenIcon from '@mui/icons-material/MenuOpen';
import AddIcon from '@mui/icons-material/Add';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ChatIcon from '@mui/icons-material/Chat';
import StorageIcon from '@mui/icons-material/Storage';
import SearchIcon from '@mui/icons-material/Search';
import ExtensionIcon from '@mui/icons-material/Extension';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import HistoryIcon from '@mui/icons-material/History';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { useThemeMode } from '../../theme/ThemeProvider';
import { useRecentHistory } from '../../hooks/useRecentHistory';
import { SIDEBAR_WIDTH_COLLAPSED, SIDEBAR_WIDTH_EXPANDED } from './constants';

const TEXT_REVEAL_EASING = 'cubic-bezier(0.2, 0, 0, 1)';
const TEXT_REVEAL_DURATION_MS = 180;

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
  { path: '/general-chat', label: '普通代理', icon: SmartToyIcon, end: true },
  { path: '/kb-chat', label: '知识库问答', icon: ChatIcon },
  { path: '/knowledge-bases', label: '知识库管理', icon: StorageIcon },
  { path: '/research', label: '深度研究', icon: SearchIcon },
  { path: '/extensions', label: 'MCP扩展', icon: ExtensionIcon },
];

export interface SidebarProps {
  expanded: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  onNewChat: () => void;
}

export function Sidebar({
  expanded,
  onToggle,
  mobileOpen,
  onMobileClose,
  onNewChat,
}: SidebarProps) {
  const theme = useTheme();
  const pathname = usePathname();
  const router = useRouter();
  const { resolvedMode, toggleMode } = useThemeMode();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const { sessions: recentSessions, removeSession } = useRecentHistory();
  const textRevealTransition = theme.transitions.create(['max-width', 'opacity'], {
    duration: TEXT_REVEAL_DURATION_MS,
    easing: TEXT_REVEAL_EASING,
  });

  const sidebarContent = (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.default',
        borderRight: 1,
        borderColor: 'divider',
      }}
    >
      {/* 顶部 Logo 区域 */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          p: 2,
          minHeight: 64,
        }}
      >
        <Box
          sx={{
            width: 40,
            height: 40,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #4285f4 0%, #34a853 50%, #fbbc04 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontWeight: 700,
            fontSize: 18,
            flexShrink: 0,
          }}
        >
          K
        </Box>
        <Box
          sx={{
            maxWidth: expanded ? 160 : 0,
            opacity: expanded ? 1 : 0,
            overflow: 'hidden',
            transition: textRevealTransition,
          }}
        >
          <Typography variant="h6" fontWeight={600} sx={{ whiteSpace: 'nowrap', color: 'primary.main' }}>
            知识代理
          </Typography>
        </Box>
      </Box>

      {/* 新对话按钮 */}
      <Box sx={{ px: 2, pb: 2 }}>
        <Tooltip title={expanded ? '' : '新对话'} placement="right">
          <ListItemButton
            onClick={onNewChat}
            sx={{
              borderRadius: 6,
              bgcolor: 'background.paper',
              border: 1,
              borderColor: 'divider',
              '&:hover': {
                bgcolor: alpha(theme.palette.primary.main, 0.08),
                borderColor: alpha(theme.palette.primary.main, 0.24),
              },
            }}
          >
            <AddIcon sx={{ mr: expanded ? 1.5 : 0 }} />
            <Box
              sx={{
                maxWidth: expanded ? 120 : 0,
                opacity: expanded ? 1 : 0,
                overflow: 'hidden',
                transition: textRevealTransition,
              }}
            >
              <Typography variant="body2" fontWeight={500} sx={{ whiteSpace: 'nowrap' }}>
                新对话
              </Typography>
            </Box>
          </ListItemButton>
        </Tooltip>
      </Box>

      {/* 主导航 */}
      <List sx={{ px: 1, flex: 1, overflowY: 'auto' }}>
        {navItems.map(({ path, label, icon: Icon, end }) => {
          const isActive = end ? pathname === path : pathname.startsWith(path);
          return (
            <ListItem key={path} disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={expanded ? '' : label} placement="right">
                <ListItemButton
                  component={Link}
                  href={path}
                  onMouseEnter={() => preloadRoute(path, router)}
                  onFocus={() => preloadRoute(path, router)}
                  onClick={isMobile ? onMobileClose : undefined}
                  sx={{
                    borderRadius: 6,
                    minHeight: 48,
                    justifyContent: expanded ? 'flex-start' : 'center',
                    px: expanded ? 2 : 1.5,
                    bgcolor: isActive
                      ? alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.12 : 0.16)
                      : 'transparent',
                    '&:hover': {
                      bgcolor: isActive
                        ? alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.16 : 0.2)
                        : 'action.hover',
                    },
                  }}
                >
                  <ListItemIcon
                    sx={{
                      minWidth: 0,
                      mr: expanded ? 2 : 0,
                      justifyContent: 'center',
                      color: isActive ? 'primary.main' : 'text.secondary',
                    }}
                  >
                    <Icon />
                  </ListItemIcon>
                  <Box
                    sx={{
                      maxWidth: expanded ? 180 : 0,
                      opacity: expanded ? 1 : 0,
                      overflow: 'hidden',
                      transition: textRevealTransition,
                    }}
                  >
                    <ListItemText
                      primary={label}
                      primaryTypographyProps={{
                        fontSize: 14,
                        fontWeight: isActive ? 600 : 400,
                        color: isActive ? 'primary.main' : 'text.primary',
                        whiteSpace: 'nowrap',
                      }}
                    />
                  </Box>
                </ListItemButton>
              </Tooltip>
            </ListItem>
          );
        })}

        {/* Recent 历史 */}
        {expanded && recentSessions.length > 0 && (
          <>
            <Divider sx={{ my: 2 }} />
            <Box sx={{ px: 1.5, pb: 1 }}>
              <Typography
                variant="overline"
                color="text.secondary"
                sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
              >
                <HistoryIcon sx={{ fontSize: 16 }} />
                最近对话
              </Typography>
            </Box>
            {recentSessions.slice(0, 5).map((session) => (
              <ListItem
                key={session.sessionId}
                disablePadding
                sx={{ mb: 0.5 }}
                secondaryAction={
                  <IconButton
                    edge="end"
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSession(session.sessionId);
                    }}
                    sx={{ opacity: 0.6, '&:hover': { opacity: 1 } }}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                }
              >
                <ListItemButton
                  component={Link}
                  href={`${session.type === 'kb_chat' ? '/kb-chat' : '/general-chat'}?sessionId=${session.sessionId}`}
                  onClick={isMobile ? onMobileClose : undefined}
                  sx={{
                    borderRadius: 6,
                    py: 1,
                    px: 2,
                    '&:hover': {
                      bgcolor: 'action.hover',
                    },
                  }}
                >
                  <ListItemText
                    primary={session.title || '未命名对话'}
                    primaryTypographyProps={{
                      fontSize: 13,
                      noWrap: true,
                      color: 'text.secondary',
                    }}
                  />
                </ListItemButton>
              </ListItem>
            ))}
          </>
        )}
      </List>

      {/* 底部操作区 */}
      <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider' }}>
        <List dense disablePadding>
          <ListItem disablePadding>
            <Tooltip
              title={expanded ? '' : resolvedMode === 'light' ? '深色模式' : '浅色模式'}
              placement="right"
            >
              <ListItemButton
                onClick={toggleMode}
                sx={{
                  borderRadius: 6,
                  justifyContent: expanded ? 'flex-start' : 'center',
                  px: expanded ? 2 : 1.5,
                }}
              >
                <ListItemIcon sx={{ minWidth: 0, mr: expanded ? 2 : 0, justifyContent: 'center' }}>
                  {resolvedMode === 'light' ? <Brightness4Icon /> : <Brightness7Icon />}
                </ListItemIcon>
                {expanded && (
                  <ListItemText
                    primary={resolvedMode === 'light' ? '深色模式' : '浅色模式'}
                    primaryTypographyProps={{ fontSize: 14 }}
                  />
                )}
              </ListItemButton>
            </Tooltip>
          </ListItem>
        </List>
      </Box>

      {/* 折叠按钮（仅桌面端显示） */}
      {!isMobile && (
        <Box sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}>
          <Tooltip title={expanded ? '收起侧边栏' : '展开侧边栏'} placement="right">
            <IconButton onClick={onToggle} sx={{ width: '100%', borderRadius: 3 }}>
              {expanded ? <MenuOpenIcon /> : <MenuIcon />}
            </IconButton>
          </Tooltip>
        </Box>
      )}
    </Box>
  );

  // 移动端使用 Drawer
  if (isMobile) {
    return (
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={onMobileClose}
        ModalProps={{ keepMounted: true }}
        PaperProps={{
          sx: {
            width: SIDEBAR_WIDTH_EXPANDED,
            boxSizing: 'border-box',
          },
        }}
      >
        {sidebarContent}
      </Drawer>
    );
  }

  // 桌面端使用固定侧边栏
  return (
    <Box
      sx={{
        width: expanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED,
        flexShrink: 0,
        height: '100vh',
        position: 'sticky',
        top: 0,
        overflow: 'hidden',
        transition: theme.transitions.create('width', {
          duration: 200,
          easing: TEXT_REVEAL_EASING,
        }),
      }}
    >
      {sidebarContent}
    </Box>
  );
}

export { SIDEBAR_WIDTH_EXPANDED, SIDEBAR_WIDTH_COLLAPSED };





