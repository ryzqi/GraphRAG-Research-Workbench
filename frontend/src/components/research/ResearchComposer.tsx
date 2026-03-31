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
      <Stack spacing={1.25}>
        <Paper
          variant="outlined"
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: { xs: 1.5, md: 2 },
            py: 1,
            borderRadius: 999,
            borderColor: props.validationError ? 'error.main' : 'rgba(223, 225, 229, 0.96)',
            bgcolor: '#ffffff',
            boxShadow: '0 1px 6px rgba(32, 33, 36, 0.14)',
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
              minWidth: { xs: 88, md: 104 },
              minHeight: 42,
              px: 2.25,
              borderRadius: 999,
              bgcolor: '#1a73e8',
              color: '#fff',
              boxShadow: 'none',
              '&:hover': {
                bgcolor: '#1765cc',
                boxShadow: 'none',
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
