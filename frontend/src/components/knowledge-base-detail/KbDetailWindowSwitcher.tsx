import { Paper, Stack, Tab, Tabs, Typography } from '@mui/material';

export interface KbDetailWindowTabItem {
  key: string;
  label: string;
  chunkCount: number;
}

interface KbDetailWindowSwitcherProps {
  items: KbDetailWindowTabItem[];
  activeKey: string | null;
  onChange: (key: string) => void;
}

export function KbDetailWindowSwitcher({
  items,
  activeKey,
  onChange,
}: KbDetailWindowSwitcherProps) {
  return (
    <Paper
      variant='outlined'
      sx={{
        borderRadius: 3,
        borderColor: 'divider',
        overflow: 'hidden',
      }}
    >
      <Stack
        direction='row'
        spacing={1}
        alignItems='center'
        justifyContent='space-between'
        sx={{ px: 1.5, pt: 1.25 }}
      >
        <Typography variant='overline' color='text.secondary'>
          分块窗口
        </Typography>
      </Stack>
      {items.length === 0 || activeKey === null ? (
        <Typography
          variant='body2'
          color='text.secondary'
          sx={{ px: 1.5, pb: 1.35 }}
        >
          当前文档暂无可切换的分块窗口。
        </Typography>
      ) : (
        <Tabs
          value={activeKey}
          onChange={(_, value: string) => onChange(value)}
          variant={items.length <= 3 ? 'fullWidth' : 'scrollable'}
          scrollButtons={items.length <= 3 ? false : 'auto'}
          allowScrollButtonsMobile={items.length > 3}
          sx={{
            minHeight: 56,
            px: 0.5,
            '& .MuiTab-root': {
              minHeight: 56,
              alignItems: 'flex-start',
              textTransform: 'none',
            },
          }}
        >
          {items.map((item) => (
            <Tab
              key={item.key}
              value={item.key}
              label={
                <Stack spacing={0.2} alignItems='flex-start'>
                  <Typography variant='body2' fontWeight={600}>
                    {item.label}
                  </Typography>
                  <Typography variant='caption' color='text.secondary'>
                    {item.chunkCount} 块
                  </Typography>
                </Stack>
              }
            />
          ))}
        </Tabs>
      )}
    </Paper>
  );
}
