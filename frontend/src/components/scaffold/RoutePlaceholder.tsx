import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

interface RoutePlaceholderProps {
  group: 'chat' | 'knowledge-bases' | 'research' | 'extensions' | 'evaluations';
  route: string;
  title: string;
  notes: string;
  checklist: string[];
}

export function RoutePlaceholder({ group, route, title, notes, checklist }: RoutePlaceholderProps) {
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
          <Typography variant="body1" color="text.secondary">
            {notes}
          </Typography>
        </Box>

        <Divider />

        <Box>
          <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
            Stage-2 implementation checklist
          </Typography>
          <Stack component="ul" spacing={0.75} sx={{ pl: 2, m: 0 }}>
            {checklist.map((item) => (
              <Typography component="li" key={item} variant="body2" color="text.secondary">
                {item}
              </Typography>
            ))}
          </Stack>
        </Box>

        <Alert severity="info">
          This page remains intentionally lightweight for incremental feature hardening on the Next.js app.
        </Alert>
      </Stack>
    </Paper>
  );
}

