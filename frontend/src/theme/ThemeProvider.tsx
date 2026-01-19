/**
 * MD3 主题切换 Provider
 * 支持 Light/Dark/System 模式，持久化用户选择
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import { ThemeProvider as MuiThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { lightTheme, darkTheme } from './index';

// ============================================================================
// 类型定义
// ============================================================================

export type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeContextValue {
  /** 当前主题模式设置 */
  mode: ThemeMode;
  /** 实际生效的主题（light 或 dark） */
  resolvedMode: 'light' | 'dark';
  /** 切换主题模式 */
  setMode: (mode: ThemeMode) => void;
  /** 切换 light/dark */
  toggleMode: () => void;
}

// ============================================================================
// Context
// ============================================================================

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const STORAGE_KEY = 'theme-mode';

/** 获取系统偏好主题 */
function getSystemPreference(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

/** 从 localStorage 读取主题设置 */
function getStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return 'system';
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  return 'system';
}

// ============================================================================
// Provider 组件
// ============================================================================

interface Md3ThemeProviderProps {
  children: ReactNode;
  /** 默认主题模式 */
  defaultMode?: ThemeMode;
}

export function Md3ThemeProvider({
  children,
  defaultMode,
}: Md3ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    return defaultMode ?? getStoredMode();
  });

  const [systemPreference, setSystemPreference] = useState<'light' | 'dark'>(
    getSystemPreference
  );

  // 监听系统主题变化
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const handleChange = (e: MediaQueryListEvent) => {
      setSystemPreference(e.matches ? 'dark' : 'light');
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // 计算实际生效的主题
  const resolvedMode = useMemo<'light' | 'dark'>(() => {
    if (mode === 'system') {
      return systemPreference;
    }
    return mode;
  }, [mode, systemPreference]);

  // 选择对应的 MUI 主题
  const theme = useMemo(() => {
    return resolvedMode === 'dark' ? darkTheme : lightTheme;
  }, [resolvedMode]);

  // 设置主题模式（带持久化）
  const setMode = useCallback((newMode: ThemeMode) => {
    setModeState(newMode);
    localStorage.setItem(STORAGE_KEY, newMode);
  }, []);

  // 切换 light/dark
  const toggleMode = useCallback(() => {
    setMode(resolvedMode === 'light' ? 'dark' : 'light');
  }, [resolvedMode, setMode]);

  const contextValue = useMemo<ThemeContextValue>(
    () => ({
      mode,
      resolvedMode,
      setMode,
      toggleMode,
    }),
    [mode, resolvedMode, setMode, toggleMode]
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      <MuiThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeContext.Provider>
  );
}

// ============================================================================
// Hook
// ============================================================================

/** 获取主题切换功能 */
export function useThemeMode(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useThemeMode must be used within Md3ThemeProvider');
  }
  return context;
}
