/**
 * 欢迎屏幕组件
 * Gemini 风格的居中欢迎界面
 */
import { Box, Stack, Typography, Chip } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import { motion } from 'framer-motion';

interface SuggestionChip {
  label: string;
  value: string;
}

interface WelcomeScreenProps {
  title?: string;
  subtitle?: string;
  suggestions?: SuggestionChip[];
  onSuggestionClick?: (value: string) => void;
  disabled?: boolean;
}

export function WelcomeScreen({
  title = '你好，需要我为你做些什么？',
  subtitle = '输入你的目标，我会拆解步骤并提供可执行的建议。',
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
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.4, ease: [0.2, 0, 0, 1] }}
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
      </motion.div>

      {/* 标题 */}
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.1, ease: [0.2, 0, 0, 1] }}
      >
        <Typography
          variant="h4"
          fontWeight={400}
          sx={{
            mb: 2,
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
      </motion.div>

      {/* 副标题 */}
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.2, ease: [0.2, 0, 0, 1] }}
      >
        <Typography
          variant="body1"
          color="text.secondary"
          sx={{ maxWidth: 500, mb: 4 }}
        >
          {subtitle}
        </Typography>
      </motion.div>

      {/* 建议 Chips */}
      {suggestions.length > 0 && (
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.3, ease: [0.2, 0, 0, 1] }}
        >
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
        </motion.div>
      )}
    </Box>
  );
}

// 建议 Chips 独立导出
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
