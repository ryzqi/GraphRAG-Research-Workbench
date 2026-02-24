import type { RefObject } from 'react';
import { Box } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { InputComposer } from './InputComposer';

interface KbChatInputPanelProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
  disabled: boolean;
  loading: boolean;
  hasPendingClarification: boolean;
  composerRef: RefObject<HTMLDivElement | null>;
}

export function KbChatInputPanel({
  value,
  onChange,
  onSend,
  disabled,
  loading,
  hasPendingClarification,
  composerRef,
}: KbChatInputPanelProps) {
  return (
    <Box
      ref={composerRef}
      sx={{
        position: 'sticky',
        bottom: 0,
        p: { xs: 1, md: 1.25 },
        bgcolor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.background.paper, 0.88)
            : alpha(theme.palette.background.paper, 0.58),
        borderTop: 1,
        borderColor: (theme) => alpha(theme.palette.divider, 0.75),
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        zIndex: 10,
      }}
    >
      <Box sx={{ maxWidth: 900, mx: 'auto' }}>
        <InputComposer
          value={value}
          onChange={onChange}
          onSend={onSend}
          disabled={disabled}
          loading={loading}
          placeholder={hasPendingClarification ? '请先补充上方澄清信息...' : '输入你的问题...'}
          showShortcutHint={false}
        />
      </Box>
    </Box>
  );
}
