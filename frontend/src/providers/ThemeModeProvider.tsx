'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider as MuiThemeProvider } from '@mui/material/styles';
import { createAppTheme, type AppThemeMode } from '@/theme/createAppTheme';

type ThemeMode = AppThemeMode | 'system';

interface ThemeModeContextValue {
  mode: ThemeMode;
  resolvedMode: AppThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

const STORAGE_KEY = 'frontend-theme-mode';
const ThemeModeContext = createContext<ThemeModeContextValue | undefined>(undefined);

function getSystemMode(): AppThemeMode {
  if (typeof window === 'undefined') {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getStoredMode(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'system';
  }
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  return 'system';
}

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>('system');
  const [systemMode, setSystemMode] = useState<AppThemeMode>('light');

  useEffect(() => {
    setModeState(getStoredMode());
    setSystemMode(getSystemMode());

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (event: MediaQueryListEvent) => {
      setSystemMode(event.matches ? 'dark' : 'light');
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  const resolvedMode = mode === 'system' ? systemMode : mode;

  const theme = useMemo(() => createAppTheme(resolvedMode), [resolvedMode]);

  const setMode = useCallback((nextMode: ThemeMode) => {
    setModeState(nextMode);
    window.localStorage.setItem(STORAGE_KEY, nextMode);
  }, []);

  const toggleMode = useCallback(() => {
    setMode(resolvedMode === 'light' ? 'dark' : 'light');
  }, [resolvedMode, setMode]);

  const value = useMemo<ThemeModeContextValue>(
    () => ({
      mode,
      resolvedMode,
      setMode,
      toggleMode,
    }),
    [mode, resolvedMode, setMode, toggleMode]
  );

  return (
    <ThemeModeContext.Provider value={value}>
      <MuiThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode(): ThemeModeContextValue {
  const context = useContext(ThemeModeContext);
  if (!context) {
    throw new Error('useThemeMode must be used within ThemeModeProvider');
  }
  return context;
}

