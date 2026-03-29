import LaunchIcon from '@mui/icons-material/Launch';
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';

import type { EvidenceItem } from '../../services/chats';
import { resolveGeneralChatSources } from '../../services/generalChatSources';

interface GeneralChatSourceChipsProps {
  evidence: EvidenceItem[];
}

export function GeneralChatSourceChips({ evidence }: GeneralChatSourceChipsProps) {
  const sources = resolveGeneralChatSources(evidence);
  if (sources.length === 0) {
    return null;
  }

  return (
    <Stack spacing={1}>
      <Stack direction='row' spacing={0.75} alignItems='center' useFlexGap flexWrap='wrap'>
        <Typography variant='caption' color='text.secondary' sx={{ fontWeight: 700 }}>
          参考来源
        </Typography>
        {sources.map((source) => (
          <Tooltip key={source.key} title={source.title} placement='top'>
            <Chip
              component='a'
              clickable
              href={source.url}
              target='_blank'
              rel='noreferrer'
              size='small'
              variant='outlined'
              icon={<LaunchIcon fontSize='small' />}
              label={source.domain}
              sx={{
                height: 22,
                borderRadius: 999,
                '& .MuiChip-label': {
                  px: 1,
                  fontWeight: 600,
                },
              }}
            />
          </Tooltip>
        ))}
      </Stack>
      <Box sx={{ display: 'none' }} aria-hidden='true'>
        {sources.map((source) => source.title).join(' | ')}
      </Box>
    </Stack>
  );
}
