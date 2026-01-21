/**
 * Gemini 风格侧边栏组件
 * 支持桌面端可折叠、移动端 Drawer 模式
 */
import { NavLink, useLocation } from 'react-router-dom';
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
import { motion, AnimatePresence } from 'framer-motion';
import MenuIcon from '@mui/icons-material/Menu';
import MenuOpenIcon from '@mui/icons-material/MenuOpen';
import AddIcon from '@mui/icons-material/Add';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ChatIcon from '@mui/icons-material/Chat';
import StorageIcon from '@mui/icons-material/Storage';
import SearchIcon from '@mui/icons-material/Search';
import ExtensionIcon from '@mui/icons-material/Extension';
import AssessmentIcon from '@mui/icons-material/Assessment';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import HistoryIcon from '@mui/icons-material/History';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { useThemeMode } from '../../theme/ThemeProvider';
import type { RecentSession } from '../../hooks/useRecentHistory';

// 路由预加载配置
const routePreloaders: Record<string, () => Promise<unknown>> = {
  '/': () => import('../../pages/GeneralChatPage'),
  '/kb-chat': () => import('../../pages/KbChatPage'),
  '/general-chat': () => import('../../pages/GeneralChatPage'),
  '/knowledge-bases': () => import('../../pages/KnowledgeBasesPage'),
  '/research': () => import('../../pages/ResearchPage'),
  '/extensions': () => import('../../pages/ExtensionsPage'),
  '/evaluations': () => import('../../pages/EvaluationsPage'),
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

// 侧边栏宽度常量
const SIDEBAR_WIDTH_EXPANDED = 260;
const SIDEBAR_WIDTH_COLLAPSED = 72;

interface SidebarProps {
  expanded: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  recentSessions: RecentSession[];
  onNewChat: () => void;
  onRemoveSession?: (sessionId: string) => void;
}

export function Sidebar({
  expanded,
  onToggle,
  mobileOpen,
  onMobileClose,
  recentSessions,
  onNewChat,
  onRemoveSession,
}: SidebarProps) {
  const theme = useTheme();
  const location = useLocation();
  const { resolvedMode, toggleMode } = useThemeMode();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  const sidebarContent = (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: theme.palette.mode === 'light' ? '#f0f4f9' : '#1e1f20',
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
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: 'auto' }}
              exit={{ opacity: 0, width: 0 }}
              transition={{ duration: 0.2 }}
            >
              <Typography
                variant="h6"
                fontWeight={600}
                sx={{ whiteSpace: 'nowrap', color: 'primary.main' }}
              >
                知识代理
              </Typography>
            </motion.div>
          )}
        </AnimatePresence>
      </Box>

      {/* 新对话按钮 */}
      <Box sx={{ px: 2, pb: 2 }}>
        <Tooltip title={expanded ? '' : '新对话'} placement="right">
          <ListItemButton
            onClick={onNewChat}
            sx={{
              borderRadius: 6,
              bgcolor: theme.palette.mode === 'light' ? '#dde3ea' : '#37393b',
              '&:hover': {
                bgcolor: theme.palette.mode === 'light' ? '#c2e7ff' : '#4d5156',
              },
              justifyContent: expanded ? 'flex-start' : 'center',
              px: expanded ? 2 : 1.5,
              py: 1.5,
            }}
          >
            <AddIcon sx={{ mr: expanded ? 1.5 : 0 }} />
            <AnimatePresence>
              {expanded && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: 'auto' }}
                  exit={{ opacity: 0, width: 0 }}
                >
                  <Typography variant="body2" fontWeight={500} sx={{ whiteSpace: 'nowrap' }}>
                    新对话
                  </Typography>
                </motion.span>
              )}
            </AnimatePresence>
          </ListItemButton>
        </Tooltip>
      </Box>

      {/* 主导航 */}
      <List sx={{ px: 1, flex: 1, overflowY: 'auto' }}>
        {navItems.map(({ path, label, icon: Icon, end }) => {
          const isActive = end ? location.pathname === path : location.pathname.startsWith(path);
          return (
            <ListItem key={path} disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={expanded ? '' : label} placement="right">
                <ListItemButton
                  component={NavLink}
                  to={path}
                  onMouseEnter={() => preloadRoute(path)}
                  onFocus={() => preloadRoute(path)}
                  onClick={isMobile ? onMobileClose : undefined}
                  sx={{
                    borderRadius: 6,
                    minHeight: 48,
                    justifyContent: expanded ? 'flex-start' : 'center',
                    px: expanded ? 2 : 1.5,
                    bgcolor: isActive
                      ? theme.palette.mode === 'light'
                        ? '#c2e7ff'
                        : '#004a77'
                      : 'transparent',
                    '&:hover': {
                      bgcolor: isActive
                        ? theme.palette.mode === 'light'
                          ? '#a8d4ff'
                          : '#005a8f'
                        : theme.palette.mode === 'light'
                          ? '#e3e8ed'
                          : '#37393b',
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
                  <AnimatePresence>
                    {expanded && (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
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
                      </motion.div>
                    )}
                  </AnimatePresence>
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
                  onRemoveSession && (
                    <IconButton
                      edge="end"
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveSession(session.sessionId);
                      }}
                      sx={{ opacity: 0.6, '&:hover': { opacity: 1 } }}
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  )
                }
              >
                <ListItemButton
                  component={NavLink}
                  to={`${
                    session.type === 'kb_chat' ? '/kb-chat' : '/'
                  }?sessionId=${session.sessionId}`}
                  sx={{
                    borderRadius: 6,
                    py: 1,
                    px: 2,
                    '&:hover': {
                      bgcolor: theme.palette.mode === 'light' ? '#e3e8ed' : '#37393b',
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
    <motion.div
      animate={{ width: expanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED }}
      transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
      style={{
        flexShrink: 0,
        height: '100vh',
        position: 'sticky',
        top: 0,
        overflow: 'hidden',
      }}
    >
      {sidebarContent}
    </motion.div>
  );
}

export { SIDEBAR_WIDTH_EXPANDED, SIDEBAR_WIDTH_COLLAPSED };
