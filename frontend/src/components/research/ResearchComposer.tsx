import { Paper, Stack, TextField, Typography } from '@mui/material';

import { ResearchPlanningHero } from './ResearchPlanningHero';
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
    <Stack spacing={2.5}>
      <ResearchPlanningHero />
      <Paper
        variant="outlined"
        sx={{
          p: { xs: 2, md: 3 },
          borderRadius: 5,
          borderColor: 'rgba(148, 163, 184, 0.2)',
          bgcolor: '#101418',
          color: '#f8fafc',
          boxShadow: '0 28px 80px rgba(2, 6, 23, 0.28)',
        }}
      >
        <Stack spacing={2.5}>
          <Stack spacing={1}>
            <Typography
              variant="overline"
              sx={{
                letterSpacing: '0.24em',
                color: 'rgba(226, 232, 240, 0.64)',
              }}
            >
              research planning
            </Typography>
            <Typography variant="h5" fontWeight={600}>
              用一句问题开启研究前规划
            </Typography>
            <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.72)' }}>
              计划阶段只呈现问题、必要澄清与计划消息。确认后，研究才会正式开始。
            </Typography>
          </Stack>
          <TextField
            fullWidth
            multiline
            minRows={5}
            value={props.question}
            onChange={(event) => props.onQuestionChange(event.target.value)}
            placeholder="例如：比较 Tavily、Jina Reader 与 SearXNG 在深度研究入口中的定位与边界。"
            error={Boolean(props.validationError)}
            helperText={
              props.validationError ??
              '研究会先收敛问题，再进入正式执行。'
            }
            slotProps={{
              input: {
                sx: {
                  color: '#f8fafc',
                  alignItems: 'flex-start',
                  bgcolor: 'rgba(15, 23, 42, 0.72)',
                  borderRadius: 3,
                },
              },
              formHelperText: {
                sx: {
                  color: props.validationError ? undefined : 'rgba(226, 232, 240, 0.64)',
                  mx: 0,
                  mt: 1,
                },
              },
            }}
            sx={{
              '& .MuiOutlinedInput-root': {
                alignItems: 'flex-start',
                borderRadius: 3,
                '& fieldset': {
                  borderColor: 'rgba(148, 163, 184, 0.24)',
                },
                '&:hover fieldset': {
                  borderColor: 'rgba(226, 232, 240, 0.42)',
                },
                '&.Mui-focused fieldset': {
                  borderColor: 'rgba(248, 250, 252, 0.78)',
                },
              },
              '& .MuiInputBase-input::placeholder': {
                color: 'rgba(226, 232, 240, 0.42)',
                opacity: 1,
              },
            }}
          />
          <Button
            variant="contained"
            onClick={props.onStart}
            loading={props.loading}
            sx={{
              alignSelf: 'flex-start',
              minHeight: 44,
              px: 2.25,
              borderRadius: 999,
              bgcolor: '#f8fafc',
              color: '#020617',
              '&:hover': {
                bgcolor: '#e2e8f0',
              },
            }}
          >
            生成研究计划
          </Button>
        </Stack>
      </Paper>
    </Stack>
  );
}
