import { Box, Paper, Stack, Typography } from '@mui/material';

import { EvidenceList } from '../EvidenceList';
import type { EvidenceItem } from '../../services/chats';

interface KbChatEvidencePanelProps {
  evidence: EvidenceItem[];
}

export function KbChatEvidencePanel({ evidence }: KbChatEvidencePanelProps) {
  return (
    <Paper variant='outlined' sx={{ p: 2, borderRadius: 2.5, minHeight: 220 }}>
      <Stack spacing={1.5}>
        <Typography variant='subtitle2' fontWeight={700}>
          证据与来源
        </Typography>
        {evidence.length > 0 ? (
          <EvidenceList evidence={evidence} />
        ) : (
          <Box sx={{ color: 'text.secondary', fontSize: 13 }}>当前回答暂无证据片段。</Box>
        )}
      </Stack>
    </Paper>
  );
}
