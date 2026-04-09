export const researchWorkbenchColors = {
  pageBackground: '#f6f8fc',
  surface: '#ffffff',
  surfaceMuted: '#f2f5fb',
  surfaceTint: '#edf2fb',
  surfaceBase: '#e8eef8',
  primary: '#1a66d9',
  primaryHover: '#1258be',
  primaryContainer: '#2f7be6',
  secondary: '#12864f',
  tertiary: '#c35a18',
  text: '#1f2430',
  mutedText: '#5e6577',
  subtleText: '#8b93a7',
  border: 'rgba(42, 57, 89, 0.1)',
  softBorder: 'rgba(42, 57, 89, 0.06)',
  strongBorder: 'rgba(42, 57, 89, 0.16)',
  accentBackground: 'rgba(26, 102, 217, 0.08)',
  rail: 'rgba(26, 102, 217, 0.14)',
  shadow: '0 22px 54px rgba(32, 48, 86, 0.08)',
  ambientShadow: '0 14px 32px rgba(32, 48, 86, 0.06)',
  glow: '0 0 0 4px rgba(26, 102, 217, 0.12)',
} as const;

export const researchDisplayFont =
  '"Plus Jakarta Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

export const researchBodyFont =
  '"Manrope", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

export const researchWorkbenchCardSx = {
  borderRadius: 32,
  border: 'none',
  bgcolor: researchWorkbenchColors.surface,
  color: researchWorkbenchColors.text,
  boxShadow: researchWorkbenchColors.shadow,
} as const;

export const researchWorkbenchInnerCardSx = {
  ...researchWorkbenchCardSx,
  bgcolor: researchWorkbenchColors.surface,
  boxShadow: researchWorkbenchColors.ambientShadow,
} as const;

export const researchWorkbenchOpenPanelSx = {
  ...researchWorkbenchCardSx,
  bgcolor: 'rgba(255, 255, 255, 0.92)',
  backdropFilter: 'blur(14px)',
} as const;

export const researchWorkbenchSectionDividerSx = {
  pt: { xs: 2.75, md: 3.25 },
  minWidth: 0,
} as const;

export const researchWorkbenchEyebrowSx = {
  color: researchWorkbenchColors.subtleText,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
} as const;
