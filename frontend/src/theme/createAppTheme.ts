import { createTheme } from '@mui/material/styles';

export type AppThemeMode = 'light' | 'dark';

export function createAppTheme(mode: AppThemeMode) {
  return createTheme({
    palette: {
      mode,
      primary: {
        main: mode === 'light' ? '#4f46e5' : '#818cf8',
      },
      background: {
        default: mode === 'light' ? '#f6f7fb' : '#111827',
        paper: mode === 'light' ? '#ffffff' : '#1f2937',
      },
    },
    shape: {
      borderRadius: 12,
    },
  });
}
