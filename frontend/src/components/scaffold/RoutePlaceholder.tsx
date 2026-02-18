import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

interface RoutePlaceholderProps {
  group: 'chat' | 'knowledge-bases' | 'research' | 'extensions';
  route: string;
  title: string;
}

export function RoutePlaceholder({ group, route, title }: RoutePlaceholderProps) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 }, borderRadius: 3 }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
          <Chip label={`Group: ${group}`} color="primary" size="small" />
          <Chip label={`Route: ${route}`} variant="outlined" size="small" />
        </Stack>

        <Box>
          <Typography variant="h5" component="h1" sx={{ mb: 1 }}>
            {title}
          </Typography>
        </Box>

      </Stack>
    </Paper>
  );
}

