export const researchWorkbenchColors = {
  pageBackground: '#f4f7fb',
  surface: '#ffffff',
  surfaceMuted: '#f7faff',
  surfaceTint: '#edf4ff',
  primary: '#1a73e8',
  primaryHover: '#1765cc',
  text: '#1f2937',
  mutedText: '#5b6678',
  subtleText: '#8a94a6',
  border: 'rgba(185, 194, 208, 0.62)',
  softBorder: 'rgba(185, 194, 208, 0.34)',
  strongBorder: 'rgba(109, 138, 184, 0.22)',
  accentBackground: 'rgba(26, 115, 232, 0.1)',
  rail: 'rgba(26, 115, 232, 0.18)',
  shadow: '0 24px 60px rgba(31, 41, 55, 0.08)',
} as const;

export const researchWorkbenchCardSx = {
  borderRadius: 24,
  borderColor: researchWorkbenchColors.border,
  bgcolor: researchWorkbenchColors.surface,
  color: researchWorkbenchColors.text,
  boxShadow: researchWorkbenchColors.shadow,
} as const;

export const researchWorkbenchInnerCardSx = {
  borderRadius: 28,
  borderColor: researchWorkbenchColors.strongBorder,
  bgcolor: 'rgba(255, 255, 255, 0.88)',
  color: researchWorkbenchColors.text,
  boxShadow: '0 18px 44px rgba(31, 41, 55, 0.08)',
  backdropFilter: 'blur(14px)',
} as const;

export const researchWorkbenchOpenPanelSx = {
  borderRadius: 30,
  border: `1px solid ${researchWorkbenchColors.softBorder}`,
  bgcolor: 'rgba(255, 255, 255, 0.84)',
  color: researchWorkbenchColors.text,
  boxShadow: researchWorkbenchColors.shadow,
  backdropFilter: 'blur(18px)',
} as const;

export const researchWorkbenchSectionDividerSx = {
  borderTop: `1px solid ${researchWorkbenchColors.softBorder}`,
  pt: { xs: 2.75, md: 3.25 },
  minWidth: 0,
} as const;

export const researchWorkbenchEyebrowSx = {
  color: researchWorkbenchColors.subtleText,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
} as const;
