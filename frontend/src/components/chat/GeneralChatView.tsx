import dynamic from 'next/dynamic';
import { Box, Chip, FormControlLabel, Switch, Typography } from '@mui/material';
import { ErrorAlert } from '../ui/ErrorAlert';
import { WelcomeScreen } from './WelcomeScreen';
import { InputComposer } from './InputComposer';
import type { ChatSession, ToolApprovalRequest } from '../../services/chats';
import type { ChatMessage } from './MessageList';

const MessageList = dynamic(
  () => import('./MessageList').then((mod) => mod.MessageList),
  { ssr: false }
);

const quickPrompts = [
  { label: '总结要点', value: '请帮我总结以下内容：' },
  { label: '生成清单', value: '请把目标拆成可执行的行动清单：' },
  { label: '优化表达', value: '请把下面内容润色成更专业的表达：' },
  { label: '风险与下一步', value: '请列出潜在风险与下一步建议：' },
];

interface GeneralChatViewProps {
  session: ChatSession | null;
  messages: ChatMessage[];
  input: string;
  loading: boolean;
  error: string | null;
  allowExternal: boolean;
  webSearchAvailable: boolean;
  hasPendingApproval: boolean;
  isInputDisabled: boolean;
  setAllowExternal: (value: boolean) => void;
  setInput: (value: string) => void;
  setError: (value: string | null) => void;
  onSend: () => Promise<void>;
  onToolApprovalSubmit: (
    messageId: string,
    runId: string,
    approval: ToolApprovalRequest
  ) => Promise<void>;
  onSuggestionClick: (value: string) => void;
}

export function GeneralChatView({
  session,
  messages,
  input,
  loading,
  error,
  allowExternal,
  webSearchAvailable,
  hasPendingApproval,
  isInputDisabled,
  setAllowExternal,
  setInput,
  setError,
  onSend,
  onToolApprovalSubmit,
  onSuggestionClick,
}: GeneralChatViewProps) {
  const sessionBadgeLabel = session
    ? session.allow_external
      ? 'MCP 已启用'
      : 'MCP 未启用'
    : allowExternal
      ? 'MCP 将启用'
      : 'MCP 已关闭';
  const webSearchBadgeLabel = webSearchAvailable ? '联网可用' : '联网不可用';

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 'calc(100vh - 64px)',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 2,
          px: { xs: 2, md: 4 },
          py: 1.5,
          position: 'sticky',
          top: 0,
          zIndex: 5,
          bgcolor: (theme) =>
            theme.palette.mode === 'light'
              ? 'rgba(240, 244, 249, 0.72)'
              : 'rgba(30, 31, 32, 0.72)',
          backdropFilter: 'blur(18px)',
          WebkitBackdropFilter: 'blur(18px)',
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={allowExternal}
              onChange={(event) => setAllowExternal(event.target.checked)}
              disabled={Boolean(session)}
            />
          }
          label={
            <Typography variant="body2" color="text.secondary">
              MCP 扩展
            </Typography>
          }
        />
        <Chip
          label={webSearchBadgeLabel}
          size="small"
          variant="outlined"
          color={webSearchAvailable ? 'success' : 'default'}
        />
        <Chip label={sessionBadgeLabel} size="small" variant="outlined" />
      </Box>

      {messages.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="你好，需要我为你做些什么？"
            suggestions={quickPrompts}
            onSuggestionClick={onSuggestionClick}
            disabled={isInputDisabled}
          />
        </Box>
      ) : (
        <MessageList
          messages={messages}
          loading={loading}
          onToolApprovalSubmit={onToolApprovalSubmit}
          approvalLoading={loading}
        />
      )}

      <ErrorAlert error={error} onClose={() => setError(null)} />

      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          p: { xs: 2, md: 3 },
          zIndex: 10,
          background: (theme) =>
            `linear-gradient(to top, ${theme.palette.background.default} 0%, rgba(0,0,0,0) 110%)`,
        }}
      >
        <Box sx={{ maxWidth: 800, mx: 'auto' }}>
          <InputComposer
            value={input}
            onChange={setInput}
            onSend={onSend}
            disabled={isInputDisabled}
            loading={loading}
            placeholder={hasPendingApproval ? '等待工具审批完成...' : '输入消息...'}
          />
        </Box>
      </Box>
    </Box>
  );
}
