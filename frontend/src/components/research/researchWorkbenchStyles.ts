export const researchWorkbenchColors = {
  pageBackground: '#f8f9fa',
  surface: '#ffffff',
  surfaceMuted: '#f3f4f5',
  surfaceTint: '#e7edf5',
  surfaceBase: '#edeeef',
  primary: '#0058bd',
  primaryHover: '#004ca3',
  primaryContainer: '#2771df',
  secondary: '#006e2c',
  tertiary: '#b51b15',
  text: '#191c1d',
  mutedText: '#424753',
  subtleText: '#727785',
  border: 'rgba(114, 119, 133, 0.16)',
  softBorder: 'rgba(114, 119, 133, 0.08)',
  strongBorder: 'rgba(114, 119, 133, 0.2)',
  accentBackground: 'rgba(0, 88, 189, 0.08)',
  rail: 'rgba(0, 88, 189, 0.14)',
  shadow: '0 24px 48px rgba(25, 28, 29, 0.06)',
  ambientShadow: '0 16px 36px rgba(25, 28, 29, 0.05)',
  glow: '0 0 0 4px rgba(39, 113, 223, 0.08)',
} as const;

export const researchDisplayFont =
  '"Plus Jakarta Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

export const researchBodyFont =
  '"Inter", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

export const researchWorkbenchCardSx = {
  borderRadius: 28,
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
  bgcolor: 'rgba(248, 249, 250, 0.86)',
  backdropFilter: 'blur(12px)',
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
