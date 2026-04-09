import SearchIcon from '@mui/icons-material/Search';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { Box, InputBase, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import { ResearchPlanningHero } from './ResearchPlanningHero';
import {
  researchBodyFont,
  researchDisplayFont,
  researchWorkbenchColors,
} from './researchWorkbenchStyles';
import { Button } from '../ui/Button';

interface ResearchComposerProps {
  question: string;
  loading: boolean;
  validationError: string | null;
  onQuestionChange: (value: string) => void;
  onStart: () => void;
}

const briefingItems = [
  { title: '边界先澄清', body: '先收窄研究问题，再组织计划与执行，避免报告在一开始就失焦。' },
  { title: '计划后执行', body: '先展示研究计划，再决定是否进入执行阶段，减少黑箱式消耗。' },
  { title: '证据可追溯', body: '最终报告会同时呈现来源账本、冲突与覆盖状态，不只给结论。' },
];

export function ResearchComposer(props: ResearchComposerProps) {
  return (
    <ResearchPlanningHero>
      <Stack spacing={{ xs: 4.5, md: 5.5 }} sx={{ width: '100%', minWidth: 0, maxWidth: 1160, mx: 'auto' }}>
        <Stack spacing={{ xs: 2.25, md: 2.75 }} sx={{ maxWidth: 920, mx: 'auto', width: '100%', textAlign: 'center' }}>
          <Typography
            variant="overline"
            sx={{
              color: researchWorkbenchColors.primary,
              letterSpacing: '0.22em',
              fontWeight: 800,
            }}
          >
            Deep Research
          </Typography>
          <Typography
            variant="h1"
            sx={{
              fontFamily: researchDisplayFont,
              fontWeight: 800,
              fontSize: { xs: '3.1rem', md: '4.9rem' },
              lineHeight: 0.98,
              letterSpacing: '-0.06em',
              color: researchWorkbenchColors.text,
            }}
          >
            深度研究
          </Typography>
          <Typography
            variant="body1"
            sx={{
              maxWidth: 760,
              mx: 'auto',
              color: researchWorkbenchColors.mutedText,
              lineHeight: 1.8,
              fontSize: { xs: '0.98rem', md: '1.04rem' },
              fontFamily: researchBodyFont,
            }}
          >
            从一个可验证的问题出发，先澄清边界，再生成研究计划，最后以可追溯证据和正式报告完成交付。
          </Typography>
        </Stack>

        <Box component="form" onSubmit={(event) => event.preventDefault()} sx={{ width: '100%' }}>
          <Paper
            variant="outlined"
            sx={{
              maxWidth: 860,
              mx: 'auto',
              p: { xs: 1.25, md: 1.45 },
              borderRadius: 999,
              borderColor: props.validationError
                ? 'error.main'
                : alpha(researchWorkbenchColors.text, 0.08),
              bgcolor: alpha('#ffffff', 0.96),
              boxShadow: '0 18px 34px rgba(25, 28, 29, 0.06)',
              transition: 'border-color 160ms ease, box-shadow 160ms ease',
              '&:focus-within': {
                borderColor: researchWorkbenchColors.primary,
                boxShadow: researchWorkbenchColors.glow,
              },
            }}
          >
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={{ xs: 1.1, sm: 1.25 }}
              alignItems={{ xs: 'stretch', sm: 'center' }}
              sx={{ minWidth: 0 }}
            >
              <Box
                sx={{
                  width: 46,
                  height: 46,
                  flexShrink: 0,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  alignSelf: { xs: 'flex-start', sm: 'center' },
                  color: alpha(researchWorkbenchColors.primary, 0.82),
                  bgcolor: alpha(researchWorkbenchColors.primary, 0.08),
                }}
              >
                <SearchIcon sx={{ fontSize: 24 }} />
              </Box>
              <InputBase
                id="research-question-input"
                fullWidth
                multiline
                minRows={1}
                maxRows={3}
                value={props.question}
                onChange={(event) => props.onQuestionChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    props.onStart();
                  }
                }}
                placeholder="输入您想要深度研究的主题或问题..."
                inputProps={{ 'aria-label': '研究问题输入框' }}
                sx={{
                  flex: 1,
                  minWidth: 0,
                  fontSize: { xs: 16, md: 17 },
                  lineHeight: 1.7,
                  color: researchWorkbenchColors.text,
                  fontFamily: researchBodyFont,
                  '& .MuiInputBase-input': {
                    py: { xs: 0.7, md: 0.85 },
                  },
                  '& textarea': {
                    resize: 'none',
                  },
                  '& .MuiInputBase-input::placeholder': {
                    color: researchWorkbenchColors.subtleText,
                    opacity: 1,
                  },
                }}
              />
              <Button
                variant="contained"
                type="button"
                onClick={props.onStart}
                loading={props.loading}
                startIcon={<AutoAwesomeRoundedIcon sx={{ fontSize: 16 }} />}
                sx={{
                  minWidth: { xs: '100%', sm: 152 },
                  minHeight: { xs: 48, md: 54 },
                  px: 3.4,
                  borderRadius: 999,
                  background: `linear-gradient(135deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
                  color: '#fff',
                  boxShadow: 'none',
                  fontWeight: 700,
                  fontSize: '0.96rem',
                  letterSpacing: '0.01em',
                  whiteSpace: 'nowrap',
                  '&:hover': {
                    background: `linear-gradient(135deg, ${researchWorkbenchColors.primaryHover} 0%, ${researchWorkbenchColors.primary} 100%)`,
                    boxShadow: 'none',
                  },
                }}
              >
                开启研究
              </Button>
            </Stack>
          </Paper>

          {props.validationError ? (
            <Typography
              variant="body2"
              color="error.main"
              sx={{ mt: 1.25, textAlign: 'center', fontWeight: 500 }}
            >
              {props.validationError}
            </Typography>
          ) : null}
        </Box>

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' },
            gap: 1.5,
            minWidth: 0,
          }}
        >
          {briefingItems.map((item, index) => (
            <Paper
              key={item.title}
              sx={{
                p: { xs: 2.25, md: 2.4 },
                borderRadius: 3.5,
                bgcolor: alpha('#ffffff', 0.84),
                boxShadow: '0 14px 28px rgba(25, 28, 29, 0.05)',
                backdropFilter: 'blur(12px)',
              }}
            >
              <Stack spacing={1.1}>
                <Typography
                  variant="caption"
                  sx={{
                    color: researchWorkbenchColors.subtleText,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    fontWeight: 700,
                  }}
                >
                  0{index + 1}
                </Typography>
                <Typography
                  variant="subtitle1"
                  sx={{
                    fontFamily: researchDisplayFont,
                    fontWeight: 800,
                    color: researchWorkbenchColors.text,
                  }}
                >
                  {item.title}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{
                    color: researchWorkbenchColors.mutedText,
                    lineHeight: 1.75,
                    fontFamily: researchBodyFont,
                  }}
                >
                  {item.body}
                </Typography>
              </Stack>
            </Paper>
          ))}
        </Box>
      </Stack>
    </ResearchPlanningHero>
  );
}
