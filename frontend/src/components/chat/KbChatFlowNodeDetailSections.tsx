import { Box, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ChatNodeDisplayItem } from '../../services/chats';
import type { KbChatFlowDetailItem } from '../../services/kbChatFlowSelectors';

type FlowDetailItem = ChatNodeDisplayItem | KbChatFlowDetailItem;

function DetailValueBlock({ value }: { value: string | string[] }) {
  if (Array.isArray(value)) {
    return (
      <Stack spacing={0.6}>
        {value.map((line, index) => (
          <Typography
            key={`${index}-${line}`}
            variant='body2'
            sx={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {line}
          </Typography>
        ))}
      </Stack>
    );
  }

  return (
    <Typography
      variant='body2'
      sx={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      {value}
    </Typography>
  );
}

function DetailSection({
  title,
  emptyText,
  items,
}: {
  title: string;
  emptyText: string;
  items: FlowDetailItem[] | null | undefined;
}) {
  return (
    <Stack spacing={0.8}>
      <Typography variant='caption' color='text.secondary'>
        {title}
      </Typography>
      {items && items.length > 0 ? (
        <Stack spacing={0.9}>
          {items.map((item) => (
            <Box
              key={`${title}-${item.key}`}
              sx={{
                border: 1,
                borderColor: 'divider',
                borderRadius: 1.5,
                p: 1,
                bgcolor: (theme) =>
                  theme.palette.mode === 'light'
                    ? alpha(theme.palette.common.black, 0.02)
                    : alpha(theme.palette.common.black, 0.16),
              }}
            >
              <Typography variant='caption' color='text.secondary' sx={{ display: 'block', mb: 0.25 }}>
                {item.label}
              </Typography>
              <DetailValueBlock value={item.value} />
            </Box>
          ))}
        </Stack>
      ) : (
        <Box
          sx={{
            border: 1,
            borderStyle: 'dashed',
            borderColor: 'divider',
            borderRadius: 1.5,
            px: 1,
            py: 0.9,
            bgcolor: (theme) =>
              theme.palette.mode === 'light'
                ? alpha(theme.palette.common.black, 0.015)
                : alpha(theme.palette.common.white, 0.03),
          }}
        >
          <Typography variant='body2' color='text.secondary'>
            {emptyText}
          </Typography>
        </Box>
      )}
    </Stack>
  );
}

export function KbChatFlowNodeDetailSections({
  inputItems,
  outputItems,
}: {
  inputItems: FlowDetailItem[] | null | undefined;
  outputItems: FlowDetailItem[] | null | undefined;
}) {
  return (
    <Stack spacing={1}>
      <DetailSection title='关键输入' emptyText='暂无关键输入' items={inputItems} />
      <DetailSection title='关键输出' emptyText='暂无关键输出' items={outputItems} />
    </Stack>
  );
}
