/**
 * Material Design 3 (Material You) 主题配置
 * 基于 Google MD3 规范，实现 Tonal Palettes 色彩系统
 */
import { createTheme, type ThemeOptions } from '@mui/material/styles';

// ============================================================================
// MD3 Tonal Palettes - 色调调色板
// ============================================================================

/** Primary 色调调色板 (基于 #1a73e8) */
const primaryPalette = {
  0: '#000000',
  10: '#001d36',
  20: '#003258',
  30: '#004a7c',
  40: '#1a73e8', // Primary (Light Mode)
  50: '#4a8df5',
  60: '#6ba5ff',
  70: '#9bc3ff',
  80: '#c9deff', // Primary (Dark Mode)
  90: '#e5efff',
  95: '#f2f6ff',
  99: '#fdfcff',
  100: '#ffffff',
};

/** Secondary 色调调色板 */
const secondaryPalette = {
  0: '#000000',
  10: '#1a1c1e',
  20: '#2f3133',
  30: '#45474a',
  40: '#5d5e61',
  50: '#76777a',
  60: '#909094',
  70: '#aaabae',
  80: '#c6c6c9',
  90: '#e2e2e5',
  95: '#f0f0f3',
  99: '#fdfcff',
  100: '#ffffff',
};

/** Error 色调调色板 */
const errorPalette = {
  0: '#000000',
  10: '#410002',
  20: '#690005',
  30: '#93000a',
  40: '#ba1a1a',
  50: '#de3730',
  60: '#ff5449',
  70: '#ff897d',
  80: '#ffb4ab',
  90: '#ffdad6',
  95: '#ffedea',
  99: '#fffbff',
  100: '#ffffff',
};

/** Neutral 色调调色板 (用于 Surface) */
const neutralPalette = {
  0: '#000000',
  4: '#0d0e11',
  6: '#121316',
  10: '#1b1b1f',
  12: '#1f1f23',
  17: '#292a2d',
  20: '#303033',
  22: '#353538',
  24: '#39393c',
  30: '#46464a',
  40: '#5e5e62',
  50: '#77777a',
  60: '#919094',
  70: '#ababaf',
  80: '#c7c6ca',
  87: '#d9d9dc',
  90: '#e3e2e6',
  92: '#e9e8ec',
  94: '#eeeff3',
  95: '#f2f2f5',
  96: '#f5f5f8',
  98: '#faf9fc',
  99: '#fdfcff',
  100: '#ffffff',
};

// ============================================================================
// MD3 Surface Containers - 表面容器色调
// ============================================================================

const surfaceContainersLight = {
  // Google Workspace / Gemini-ish light surfaces (cool tinted neutrals).
  surface: '#f0f4f9',
  surfaceDim: '#dde3ea',
  surfaceBright: '#f8fafd',
  surfaceContainerLowest: '#ffffff',
  surfaceContainerLow: '#f8fafd',
  surfaceContainer: '#eef3f8',
  surfaceContainerHigh: '#e7edf5',
  surfaceContainerHighest: '#dde3ea',
};

const surfaceContainersDark = {
  // Google Workspace / Gemini-ish dark surfaces (neutral, not pure black).
  surface: '#1e1f20',
  surfaceDim: '#17181a',
  surfaceBright: '#2b2c2d',
  surfaceContainerLowest: '#151617',
  surfaceContainerLow: '#232425',
  surfaceContainer: '#2b2c2d',
  surfaceContainerHigh: '#333437',
  surfaceContainerHighest: '#3c3d40',
};

// ============================================================================
// MD3 动画配置
// ============================================================================

export const md3Motion = {
  easing: {
    standard: 'cubic-bezier(0.2, 0, 0, 1)',
    standardDecelerate: 'cubic-bezier(0, 0, 0, 1)',
    standardAccelerate: 'cubic-bezier(0.3, 0, 1, 1)',
    emphasized: 'cubic-bezier(0.2, 0, 0, 1)',
    emphasizedDecelerate: 'cubic-bezier(0.05, 0.7, 0.1, 1)',
    emphasizedAccelerate: 'cubic-bezier(0.3, 0, 0.8, 0.15)',
  },
  duration: {
    short1: 50,
    short2: 100,
    short3: 150,
    short4: 200,
    medium1: 250,
    medium2: 300,
    medium3: 350,
    medium4: 400,
    long1: 450,
    long2: 500,
    long3: 550,
    long4: 600,
  },
};

// ============================================================================
// 主题配置工厂函数
// ============================================================================

function createMd3ThemeOptions(mode: 'light' | 'dark'): ThemeOptions {
  const isLight = mode === 'light';
  const surfaces = isLight ? surfaceContainersLight : surfaceContainersDark;

  return {
    palette: {
      mode,
      primary: {
        main: isLight ? primaryPalette[40] : primaryPalette[80],
        light: isLight ? primaryPalette[50] : primaryPalette[90],
        dark: isLight ? primaryPalette[30] : primaryPalette[70],
        contrastText: isLight ? '#ffffff' : primaryPalette[20],
      },
      secondary: {
        main: isLight ? secondaryPalette[40] : secondaryPalette[80],
        light: isLight ? secondaryPalette[50] : secondaryPalette[90],
        dark: isLight ? secondaryPalette[30] : secondaryPalette[70],
        contrastText: isLight ? '#ffffff' : secondaryPalette[20],
      },
      error: {
        main: isLight ? errorPalette[40] : errorPalette[80],
        light: isLight ? errorPalette[50] : errorPalette[90],
        dark: isLight ? errorPalette[30] : errorPalette[70],
        contrastText: isLight ? '#ffffff' : errorPalette[20],
      },
      warning: {
        main: '#f9ab00',
        light: '#fbbc04',
        dark: '#f29900',
      },
      success: {
        main: '#1e8e3e',
        light: '#34a853',
        dark: '#137333',
      },
      info: {
        main: isLight ? primaryPalette[40] : primaryPalette[80],
        light: isLight ? primaryPalette[50] : primaryPalette[90],
        dark: isLight ? primaryPalette[30] : primaryPalette[70],
      },
      background: {
        default: surfaces.surface,
        paper: surfaces.surfaceContainerLow,
      },
      text: {
        primary: isLight ? neutralPalette[10] : neutralPalette[90],
        secondary: isLight ? neutralPalette[40] : neutralPalette[70],
        disabled: isLight ? neutralPalette[60] : neutralPalette[50],
      },
      divider: isLight ? neutralPalette[87] : neutralPalette[30],
      action: {
        hover: isLight
          ? 'rgba(0, 0, 0, 0.08)'
          : 'rgba(255, 255, 255, 0.08)',
        selected: isLight
          ? 'rgba(26, 115, 232, 0.12)'
          : 'rgba(201, 222, 255, 0.12)',
        disabled: isLight
          ? 'rgba(0, 0, 0, 0.38)'
          : 'rgba(255, 255, 255, 0.38)',
        disabledBackground: isLight
          ? 'rgba(0, 0, 0, 0.12)'
          : 'rgba(255, 255, 255, 0.12)',
      },
    },
    typography: {
      fontFamily: [
        '"Google Sans"',
        '"Roboto Flex"',
        'Roboto',
        '"Noto Sans SC"',
        '-apple-system',
        'BlinkMacSystemFont',
        '"Segoe UI"',
        '"PingFang SC"',
        '"Microsoft YaHei"',
        'sans-serif',
      ].join(','),
      h1: {
        fontSize: '2rem',
        fontWeight: 500,
        letterSpacing: '-0.01em',
      },
      h2: {
        fontSize: '1.5rem',
        fontWeight: 500,
        letterSpacing: '-0.005em',
      },
      h3: {
        fontSize: '1.25rem',
        fontWeight: 500,
      },
      h4: {
        fontSize: '1.125rem',
        fontWeight: 500,
      },
      h5: {
        fontSize: '1rem',
        fontWeight: 500,
      },
      h6: {
        fontSize: '0.875rem',
        fontWeight: 500,
      },
      body1: {
        fontSize: '0.875rem',
        lineHeight: 1.5,
      },
      body2: {
        fontSize: '0.8125rem',
        lineHeight: 1.5,
      },
      button: {
        textTransform: 'none',
        fontWeight: 500,
      },
      caption: {
        fontSize: '0.75rem',
      },
    },
    shape: {
      borderRadius: 12, // MD3 默认圆角增大
    },
    transitions: {
      easing: {
        easeInOut: md3Motion.easing.standard,
        easeOut: md3Motion.easing.standardDecelerate,
        easeIn: md3Motion.easing.standardAccelerate,
        sharp: md3Motion.easing.emphasizedAccelerate,
      },
      duration: {
        shortest: md3Motion.duration.short2,
        shorter: md3Motion.duration.short3,
        short: md3Motion.duration.short4,
        standard: md3Motion.duration.medium2,
        complex: md3Motion.duration.medium4,
        enteringScreen: md3Motion.duration.medium2,
        leavingScreen: md3Motion.duration.medium1,
      },
    },
    shadows: [
      'none',
      // Level 1 - 微弱阴影
      '0 1px 2px 0 rgba(0,0,0,0.05)',
      '0 1px 3px 0 rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1)',
      // Level 2
      '0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1)',
      '0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1)',
      // Level 3
      '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)',
      '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)',
      '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)',
      '0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)',
      // Level 4
      '0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)',
      '0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)',
      '0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)',
      '0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)',
      // Level 5
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
      '0 25px 50px -12px rgba(0,0,0,0.25)',
    ],
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            scrollbarColor: isLight ? '#dadce0 transparent' : '#5f6368 transparent',
            '&::-webkit-scrollbar': {
              width: 8,
              height: 8,
            },
            '&::-webkit-scrollbar-thumb': {
              backgroundColor: isLight ? '#dadce0' : '#5f6368',
              borderRadius: 4,
            },
            '&::-webkit-scrollbar-track': {
              backgroundColor: 'transparent',
            },
          },
        },
      },
      // MD3 Button: 全圆角 Pill 样式
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 20, // MD3 全圆角
            padding: '10px 24px',
            fontWeight: 500,
            minHeight: 40,
            transition: `all ${md3Motion.duration.medium2}ms ${md3Motion.easing.standard}`,
            '&:active': {
              transform: 'scale(0.98)', // 按压微交互
            },
          },
          contained: {
            boxShadow: 'none',
            '&:hover': {
              boxShadow: '0 1px 3px rgba(0,0,0,0.12)',
              // MD3: Tonal elevation - 背景色变浅而非加深阴影
              filter: 'brightness(1.08)',
            },
          },
          outlined: {
            borderColor: isLight ? neutralPalette[50] : neutralPalette[60],
            '&:hover': {
              borderColor: isLight ? primaryPalette[40] : primaryPalette[80],
              backgroundColor: isLight
                ? 'rgba(26, 115, 232, 0.08)'
                : 'rgba(201, 222, 255, 0.08)',
            },
          },
          text: {
            '&:hover': {
              backgroundColor: isLight
                ? 'rgba(26, 115, 232, 0.08)'
                : 'rgba(201, 222, 255, 0.08)',
            },
          },
          sizeSmall: {
            padding: '6px 16px',
            minHeight: 32,
            fontSize: '0.8125rem',
            borderRadius: 16,
          },
          sizeLarge: {
            padding: '12px 28px',
            minHeight: 48,
            borderRadius: 24,
          },
        },
        defaultProps: {
          disableElevation: true,
          disableRipple: false,
        },
      },
      // MD3 Card: 增大圆角，使用 Tonal elevation
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 16, // MD3 Card 圆角
            boxShadow: 'none',
            backgroundColor: surfaces.surfaceContainerLow,
            transition: `all ${md3Motion.duration.medium2}ms ${md3Motion.easing.standard}`,
            '&:hover': {
              backgroundColor: surfaces.surfaceContainer,
            },
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none', // 移除默认渐变
          },
          outlined: {
            borderColor: isLight ? neutralPalette[87] : neutralPalette[30],
          },
        },
      },
      // MD3 TextField: 增大圆角
      MuiTextField: {
        defaultProps: {
          variant: 'outlined',
          size: 'small',
        },
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 12, // MD3 输入框圆角
              '& fieldset': {
                borderColor: isLight ? neutralPalette[50] : neutralPalette[60],
                transition: `border-color ${md3Motion.duration.short4}ms ${md3Motion.easing.standard}`,
              },
              '&:hover fieldset': {
                borderColor: isLight ? primaryPalette[40] : primaryPalette[80],
              },
              '&.Mui-focused fieldset': {
                borderColor: isLight ? primaryPalette[40] : primaryPalette[80],
                borderWidth: 2,
              },
            },
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            '& fieldset': {
              borderColor: isLight ? neutralPalette[50] : neutralPalette[60],
            },
            '&:hover fieldset': {
              borderColor: isLight ? primaryPalette[40] : primaryPalette[80],
            },
          },
          notchedOutline: {
            borderColor: isLight ? neutralPalette[50] : neutralPalette[60],
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            height: 32,
            fontSize: '0.8125rem',
            fontWeight: 500,
          },
          outlined: {
            borderColor: isLight ? neutralPalette[50] : neutralPalette[60],
          },
        },
      },
      // MD3 Dialog: 大圆角
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 28, // MD3 Dialog 圆角
            backgroundColor: surfaces.surfaceContainerHigh,
            boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
          },
        },
      },
      MuiDialogTitle: {
        styleOverrides: {
          root: {
            fontSize: '1.25rem',
            fontWeight: 500,
            padding: '24px 24px 16px',
          },
        },
      },
      MuiDialogContent: {
        styleOverrides: {
          root: {
            padding: '0 24px 24px',
          },
        },
      },
      MuiDialogActions: {
        styleOverrides: {
          root: {
            padding: '16px 24px 24px',
            gap: 8,
          },
        },
      },
      // MD3 AppBar
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundColor: surfaces.surface,
            color: isLight ? neutralPalette[10] : neutralPalette[90],
            backgroundImage: 'none',
          },
        },
        defaultProps: {
          elevation: 0,
        },
      },
      MuiToolbar: {
        styleOverrides: {
          root: {
            minHeight: 64,
            '@media (min-width: 600px)': {
              minHeight: 64,
            },
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 500,
            minWidth: 'auto',
            padding: '12px 24px',
            borderRadius: '20px 20px 0 0',
          },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: {
            height: 3,
            borderRadius: '3px 3px 0 0',
          },
        },
      },
      MuiCheckbox: {
        styleOverrides: {
          root: {
            color: isLight ? neutralPalette[50] : neutralPalette[60],
            '&.Mui-checked': {
              color: isLight ? primaryPalette[40] : primaryPalette[80],
            },
          },
        },
      },
      MuiAlert: {
        styleOverrides: {
          root: {
            borderRadius: 12,
          },
          standardError: {
            backgroundColor: isLight ? errorPalette[95] : errorPalette[20],
            color: isLight ? errorPalette[30] : errorPalette[90],
          },
          standardWarning: {
            backgroundColor: isLight ? '#fef7e0' : '#3d2e00',
            color: isLight ? '#5c4200' : '#ffe17a',
          },
          standardSuccess: {
            backgroundColor: isLight ? '#e6f4ea' : '#0d3315',
            color: isLight ? '#137333' : '#6dd58c',
          },
          standardInfo: {
            backgroundColor: isLight ? primaryPalette[95] : primaryPalette[20],
            color: isLight ? primaryPalette[30] : primaryPalette[90],
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            backgroundColor: isLight ? neutralPalette[20] : neutralPalette[90],
            color: isLight ? neutralPalette[100] : neutralPalette[10],
            fontSize: '0.75rem',
            padding: '8px 12px',
            borderRadius: 8,
          },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: {
            borderRadius: 4,
            height: 4,
            backgroundColor: isLight ? primaryPalette[90] : primaryPalette[30],
          },
          bar: {
            borderRadius: 4,
          },
        },
      },
      MuiCircularProgress: {
        defaultProps: {
          thickness: 4,
        },
      },
      // MD3 Skeleton
      MuiSkeleton: {
        styleOverrides: {
          root: {
            backgroundColor: isLight
              ? 'rgba(0, 0, 0, 0.08)'
              : 'rgba(255, 255, 255, 0.08)',
          },
          rounded: {
            borderRadius: 12,
          },
        },
      },
      // MD3 Fab
      MuiFab: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            boxShadow: '0 4px 8px rgba(0,0,0,0.15)',
          },
        },
      },
    },
  };
}

// ============================================================================
// 导出主题
// ============================================================================

/** Light Mode 主题 */
export const lightTheme = createTheme(createMd3ThemeOptions('light'));

/** Dark Mode 主题 */
export const darkTheme = createTheme(createMd3ThemeOptions('dark'));
