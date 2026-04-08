export const researchWorkbenchColors = {
  pageBackground: '#f8f9fa',
  surface: '#ffffff',
  primary: '#1a73e8',
  primaryHover: '#1765cc',
  text: '#202124',
  mutedText: '#5f6368',
  subtleText: '#80868b',
  border: 'rgba(218, 220, 224, 0.88)',
  softBorder: 'rgba(218, 220, 224, 0.72)',
  accentBackground: 'rgba(26, 115, 232, 0.08)',
} as const;

export const researchWorkbenchCardSx = {
  borderRadius: 24,
  borderColor: researchWorkbenchColors.border,
  bgcolor: researchWorkbenchColors.surface,
  color: researchWorkbenchColors.text,
  boxShadow: '0 10px 28px rgba(60, 64, 67, 0.08)',
} as const;

export const researchWorkbenchInnerCardSx = {
  borderRadius: 20,
  borderColor: researchWorkbenchColors.softBorder,
  bgcolor: researchWorkbenchColors.surface,
  color: researchWorkbenchColors.text,
  boxShadow: '0 6px 18px rgba(60, 64, 67, 0.06)',
} as const;

export const researchWorkbenchEyebrowSx = {
  color: researchWorkbenchColors.subtleText,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
} as const;
