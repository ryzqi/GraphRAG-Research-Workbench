import SearchIcon from '@mui/icons-material/Search';
import { InputBase, Paper, Stack, Typography } from '@mui/material';

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
    <ResearchPlanningHero>
      <Stack spacing={2}>
        <Paper
          variant="outlined"
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: { xs: 1.75, md: 2.25 },
            py: 1.25,
            borderRadius: 6,
            borderColor: props.validationError ? 'error.main' : 'rgba(210, 227, 252, 0.96)',
            bgcolor: 'rgba(255,255,255,0.96)',
            boxShadow: '0 22px 64px rgba(66, 133, 244, 0.10)',
            backdropFilter: 'blur(16px)',
          }}
        >
          <SearchIcon sx={{ color: '#9aa0a6' }} />
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
              fontSize: { xs: 16, md: 18 },
              lineHeight: 1.5,
              color: '#202124',
              py: 0.5,
              '& .MuiInputBase-input::placeholder': {
                color: '#80868b',
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
              px: 2.5,
              borderRadius: 999,
              bgcolor: '#1a73e8',
              color: '#fff',
              boxShadow: '0 10px 22px rgba(26, 115, 232, 0.28)',
              '&:hover': {
                bgcolor: '#1765cc',
                boxShadow: '0 12px 24px rgba(26, 115, 232, 0.32)',
              },
            }}
          >
            开始研究
          </Button>
        </Paper>

        {props.validationError ? (
          <Typography variant="body2" color="error.main" sx={{ px: 2 }}>
            {props.validationError}
          </Typography>
        ) : null}
      </Stack>
    </ResearchPlanningHero>
  );
}
