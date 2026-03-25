/**
 * 欢迎屏幕组件
 * Gemini 风格的居中欢迎界面
 */
import { Box, Stack, Typography, Chip } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';

interface SuggestionChip {
  label: string;
  value: string;
}

interface WelcomeScreenProps {
  title?: string;
  suggestions?: SuggestionChip[];
  onSuggestionClick?: (value: string) => void;
  disabled?: boolean;
}

function createFadeUpSx(delayMs: number) {
  return {
    animation: `welcomeFadeUp 400ms cubic-bezier(0.2, 0, 0, 1) ${delayMs}ms both`,
    '@keyframes welcomeFadeUp': {
      from: {
        opacity: 0,
        transform: 'translateY(20px)',
      },
      to: {
        opacity: 1,
        transform: 'translateY(0)',
      },
    },
    '@media (prefers-reduced-motion: reduce)': {
      animation: 'none',
    },
  };
}

export function WelcomeScreen({
  title = '你好，需要我为你做些什么？',
  suggestions = [],
  onSuggestionClick,
  disabled = false,
}: WelcomeScreenProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        py: { xs: 6, md: 10 },
        px: 3,
      }}
    >
      {/* Logo 动画 */}
      <Box
        sx={{
          animation: 'welcomePopIn 400ms cubic-bezier(0.2, 0, 0, 1) both',
          '@keyframes welcomePopIn': {
            from: {
              scale: 0.8,
              opacity: 0,
            },
            to: {
              scale: 1,
              opacity: 1,
            },
          },
          '@media (prefers-reduced-motion: reduce)': {
            animation: 'none',
          },
        }}
      >
        <Box
          sx={{
            width: 80,
            height: 80,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #4285F4, #9B72CB, #D96570)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            mb: 4,
            boxShadow: '0 12px 40px rgba(66, 133, 244, 0.3)',
          }}
        >
          <AutoAwesomeIcon sx={{ fontSize: 40, color: 'white' }} />
        </Box>
      </Box>

      {/* 标题 */}
      <Box sx={createFadeUpSx(100)}>
        <Typography
          variant="h4"
          fontWeight={400}
          sx={{
            mb: 4,
            background: (theme) =>
              theme.palette.mode === 'light'
                ? 'linear-gradient(135deg, #1a73e8, #34a853)'
                : 'linear-gradient(135deg, #8ab4f8, #81c995)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}
        >
          {title}
        </Typography>
      </Box>

      {/* 建议 Chips */}
      {suggestions.length > 0 && (
        <Box sx={createFadeUpSx(300)}>
          <Stack
            direction="row"
            spacing={1}
            flexWrap="wrap"
            justifyContent="center"
            useFlexGap
            sx={{ maxWidth: 600 }}
          >
            {suggestions.map((suggestion) => (
              <Chip
                key={suggestion.label}
                label={suggestion.label}
                variant="outlined"
                clickable
                disabled={disabled}
                onClick={() => onSuggestionClick?.(suggestion.value)}
                sx={{
                  borderRadius: 4,
                  px: 1,
                  py: 2.5,
                  fontSize: 14,
                  borderColor: 'divider',
                  '&:hover': {
                    bgcolor: 'action.hover',
                    borderColor: 'primary.main',
                  },
                }}
              />
            ))}
          </Stack>
        </Box>
      )}
    </Box>
  );
}

// 建议将建议项 Chips 独立导出
interface SuggestionChipsProps {
  suggestions: SuggestionChip[];
  onSelect: (value: string) => void;
  disabled?: boolean;
}

export function SuggestionChips({ suggestions, onSelect, disabled = false }: SuggestionChipsProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {suggestions.map((suggestion) => (
        <Chip
          key={suggestion.label}
          label={suggestion.label}
          variant="outlined"
          clickable
          disabled={disabled}
          onClick={() => onSelect(suggestion.value)}
          sx={{
            borderRadius: 3,
            fontSize: 13,
            borderColor: 'divider',
            '&:hover': {
              bgcolor: 'action.hover',
              borderColor: 'primary.main',
            },
          }}
        />
      ))}
    </Stack>
  );
}
