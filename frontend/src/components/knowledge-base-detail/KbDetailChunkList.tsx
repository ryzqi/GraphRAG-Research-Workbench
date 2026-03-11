import {
  Box,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Typography,
} from '@mui/material';

import { ListSkeleton } from '../ui/Skeleton';

export interface KbDetailChunkListItem {
  id: string;
  title: string;
  preview: string;
  meta: string | null;
}

interface KbDetailChunkListProps {
  items: KbDetailChunkListItem[];
  selectedChunkId: string | null;
  onSelect: (chunkId: string) => void;
  isPending: boolean;
  emptyText?: string;
}

export function KbDetailChunkList({
  items,
  selectedChunkId,
  onSelect,
  isPending,
  emptyText = '当前窗口暂无分块。',
}: KbDetailChunkListProps) {
  return (
    <Paper
      variant='outlined'
      sx={{
        height: '100%',
        minHeight: 0,
        borderRadius: 3,
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <Box sx={{ px: 1.5, py: 1.25, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant='overline' color='text.secondary'>
          当前窗口
        </Typography>
        <Typography variant='subtitle2' fontWeight={700}>
          分块列表
        </Typography>
      </Box>

      {isPending ? (
        <Box sx={{ p: 1.25 }}>
          <ListSkeleton count={8} />
        </Box>
      ) : items.length === 0 ? (
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            px: 2,
          }}
        >
          <Typography variant='body2' color='text.secondary' align='center'>
            {emptyText}
          </Typography>
        </Box>
      ) : (
        <List
          disablePadding
          sx={{ flex: 1, minHeight: 0, overflowY: 'auto', p: 1 }}
        >
          {items.map((item, index) => {
            const selected = item.id === selectedChunkId;
            return (
              <ListItemButton
                key={item.id}
                selected={selected}
                onClick={() => onSelect(item.id)}
                sx={{
                  mb: index === items.length - 1 ? 0 : 0.75,
                  borderRadius: 2.5,
                  border: 1,
                  borderColor: selected ? 'primary.main' : 'divider',
                  bgcolor: selected ? 'action.selected' : 'background.paper',
                  alignItems: 'flex-start',
                  '&.Mui-selected, &.Mui-selected:hover': {
                    bgcolor: 'action.selected',
                    borderColor: 'primary.main',
                  },
                }}
              >
                <ListItemText
                  primary={
                    <Typography variant='body2' fontWeight={700}>
                      {item.title}
                    </Typography>
                  }
                  secondary={
                    <>
                      {item.meta && (
                        <Typography
                          variant='caption'
                          color='text.secondary'
                          sx={{ mt: 0.35, display: 'block' }}
                        >
                          {item.meta}
                        </Typography>
                      )}
                      <Typography
                        variant='caption'
                        color='text.secondary'
                        sx={{
                          mt: 0.45,
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {item.preview}
                      </Typography>
                    </>
                  }
                />
              </ListItemButton>
            );
          })}
        </List>
      )}
    </Paper>
  );
}
