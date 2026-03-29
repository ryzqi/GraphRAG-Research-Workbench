import { Paper, Stack, TextField, Typography } from '@mui/material';

import type { ResearchSessionStatus } from '../../types/researchEvents';
import { Button } from '../ui/Button';

interface InterruptDecisionPanelProps {
  status: ResearchSessionStatus;
  resumeIdempotencyKey: string;
  decisionDraft: string;
  onResumeIdempotencyKeyChange: (value: string) => void;
  onDecisionDraftChange: (value: string) => void;
  onResume: (() => void | Promise<void>) | undefined;
  resumePending?: boolean;
}

export function InterruptDecisionPanel({
  status,
  resumeIdempotencyKey,
  decisionDraft,
  onResumeIdempotencyKeyChange,
  onDecisionDraftChange,
  onResume,
  resumePending = false,
}: InterruptDecisionPanelProps) {
  if (status !== 'interrupted') {
    return null;
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1" fontWeight={600}>
          中断决策
        </Typography>
        <Typography variant="body2" color="text.secondary">
          当前会话已进入 interrupted 状态。可提交 resume 幂等键与决策 JSON，继续执行研究。
        </Typography>
        <TextField
          label="Resume Idempotency Key"
          size="small"
          value={resumeIdempotencyKey}
          onChange={(event) => onResumeIdempotencyKeyChange(event.target.value)}
        />
        <TextField
          label="决策 JSON"
          multiline
          minRows={3}
          value={decisionDraft}
          onChange={(event) => onDecisionDraftChange(event.target.value)}
        />
        <Button
          variant="contained"
          onClick={() => {
            void onResume?.();
          }}
          loading={resumePending}
          sx={{ alignSelf: 'flex-start' }}
        >
          继续执行
        </Button>
      </Stack>
    </Paper>
  );
}
