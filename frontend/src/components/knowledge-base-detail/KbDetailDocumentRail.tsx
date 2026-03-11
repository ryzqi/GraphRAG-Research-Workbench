import type { ChangeEvent } from 'react';
import {
  Box,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';

import { ListSkeleton } from '../ui/Skeleton';

export interface KbDetailDocumentItem {
  id: string;
  title: string;
  chunkCountLabel: string;
}

interface KbDetailDocumentRailProps {
  items: KbDetailDocumentItem[];
  selectedId: string | null;
  filterValue: string;
  onFilterChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onSelect: (materialId: string) => void;
  isPending: boolean;
  emptyText?: string;
}

const RAIL_SCROLL_SX = {
  flex: 1,
  minHeight: 0,
  overflowY: 'auto',
  pr: 0.5,
} as const;

export function KbDetailDocumentRail({
  items,
  selectedId,
  filterValue,
  onFilterChange,
  onSelect,
  isPending,
  emptyText = '暂无可浏览文档。',
}: KbDetailDocumentRailProps) {
  return (
    <Paper
      variant='outlined'
      sx={{
        height: '100%',
        p: 1.25,
        borderRadius: 3,
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
    >
      <Stack spacing={1.1} sx={{ mb: 1.25 }}>
        <Stack spacing={0.35}>
          <Typography variant='overline' color='text.secondary'>
            文档
          </Typography>
          <Typography variant='subtitle2' fontWeight={700}>
            选择浏览对象
          </Typography>
        </Stack>
        <TextField
          size='small'
          placeholder='搜索文档'
          value={filterValue}
          onChange={onFilterChange}
          fullWidth
          InputProps={{
            startAdornment: (
              <InputAdornment position='start'>
                <SearchIcon fontSize='small' />
              </InputAdornment>
            ),
          }}
        />
      </Stack>

      {isPending ? (
        <ListSkeleton count={6} />
      ) : items.length === 0 ? (
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            px: 1,
          }}
        >
          <Typography variant='body2' color='text.secondary' align='center'>
            {emptyText}
          </Typography>
        </Box>
      ) : (
        <List disablePadding sx={RAIL_SCROLL_SX}>
          {items.map((item, index) => {
            const selected = item.id === selectedId;
            return (
              <ListItemButton
                key={item.id}
                selected={selected}
                onClick={() => onSelect(item.id)}
                sx={{
                  mb: index === items.length - 1 ? 0 : 0.75,
                  px: 1.15,
                  py: 1.1,
                  borderRadius: 2.5,
                  alignItems: 'flex-start',
                  border: 1,
                  borderColor: selected ? 'primary.main' : 'divider',
                  bgcolor: selected ? 'action.selected' : 'background.paper',
                  '&.Mui-selected, &.Mui-selected:hover': {
                    bgcolor: 'action.selected',
                    borderColor: 'primary.main',
                  },
                }}
              >
                <ListItemText
                  primary={
                    <Typography
                      variant='body2'
                      fontWeight={600}
                      sx={{
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {item.title}
                    </Typography>
                  }
                  secondary={
                    <Typography variant='caption' color='text.secondary' sx={{ mt: 0.35, display: 'block' }}>
                      {item.chunkCountLabel}
                    </Typography>
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
