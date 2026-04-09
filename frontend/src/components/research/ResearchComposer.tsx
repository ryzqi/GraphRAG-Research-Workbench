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

export function ResearchComposer(props: ResearchComposerProps) {
  return (
    <ResearchPlanningHero>
        <Stack spacing={{ xs: 4.5, md: 5.5 }} sx={{ width: '100%', minWidth: 0, maxWidth: 920, mx: 'auto' }}>
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
      </Stack>
    </ResearchPlanningHero>
  );
}
