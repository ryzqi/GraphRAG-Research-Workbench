import SearchIcon from '@mui/icons-material/Search';
import { InputBase, Paper, Stack, Typography } from '@mui/material';

import { ResearchPlanningHero } from './ResearchPlanningHero';
import {
  researchWorkbenchCardSx,
  researchWorkbenchColors,
  researchWorkbenchEyebrowSx,
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
      <Stack spacing={{ xs: 2.5, md: 3 }}>
        <Stack spacing={1} sx={{ maxWidth: 720 }}>
          <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
            Deep Research
          </Typography>
          <Typography
            variant="h3"
            sx={{
              fontWeight: 700,
              fontSize: { xs: '2rem', md: '3rem' },
              lineHeight: 1.08,
              color: researchWorkbenchColors.text,
            }}
          >
            深度研究工作台
          </Typography>
          <Typography
            variant="body1"
            sx={{
              maxWidth: 640,
              color: researchWorkbenchColors.mutedText,
              lineHeight: 1.7,
            }}
          >
            把问题拆成计划、证据和最终结论。
          </Typography>
        </Stack>

        <Paper
          variant="outlined"
          sx={{
            ...researchWorkbenchCardSx,
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            px: { xs: 2, md: 3 },
            py: { xs: 1.5, md: 1.75 },
            borderColor: props.validationError ? 'error.main' : researchWorkbenchColors.border,
            maxWidth: 1120,
          }}
        >
          <SearchIcon sx={{ color: researchWorkbenchColors.subtleText }} />
          <InputBase
            fullWidth
            multiline
            minRows={1}
            maxRows={6}
            value={props.question}
            onChange={(event) => props.onQuestionChange(event.target.value)}
            placeholder="有问题，尽管问"
            inputProps={{ 'aria-label': '研究问题输入框' }}
            sx={{
              fontSize: { xs: 16, md: 20 },
              lineHeight: 1.5,
              color: researchWorkbenchColors.text,
              py: 0.5,
              '& .MuiInputBase-input::placeholder': {
                color: researchWorkbenchColors.subtleText,
                opacity: 1,
              },
            }}
          />
          <Button
            variant="contained"
            onClick={props.onStart}
            loading={props.loading}
            sx={{
              flexShrink: 0,
              minWidth: { xs: 96, md: 116 },
              minHeight: 46,
              px: 3,
              borderRadius: 999,
              bgcolor: researchWorkbenchColors.primary,
              color: '#fff',
              boxShadow: 'none',
              '&:hover': {
                bgcolor: researchWorkbenchColors.primaryHover,
                boxShadow: 'none',
              },
            }}
          >
            开始研究
          </Button>
        </Paper>

        {props.validationError ? (
          <Typography variant="body2" color="error.main" sx={{ px: 1 }}>
            {props.validationError}
          </Typography>
        ) : null}
      </Stack>
    </ResearchPlanningHero>
  );
}
