import dynamic from 'next/dynamic';
import { Box, Chip, FormControlLabel, Switch, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { ErrorAlert } from '../ui/ErrorAlert';
import { WelcomeScreen } from './WelcomeScreen';
import { InputComposer } from './InputComposer';
import { ChatInputDock } from './ChatInputDock';
import { ChatViewport } from './ChatViewport';
import type {
  ChatSession,
  ToolApprovalRequest,
  WebSearchStatus,
} from '../../services/chats';
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
  webSearch: WebSearchStatus;
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
  webSearch,
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
  const webSearchConfiguredLabel = webSearch.configured ? '联网已配置' : '联网未配置';
  const webSearchHealthLabel = !webSearch.configured
    ? '联网未验证'
    : !webSearch.verified
      ? '联网未验证'
      : webSearch.healthy
        ? '联网已验证'
        : '联网异常';
  const webSearchHealthColor: 'default' | 'warning' | 'success' | 'error' = !webSearch.configured
    ? 'default'
    : !webSearch.verified
      ? 'warning'
      : webSearch.healthy
        ? 'success'
        : 'error';

  return (
    <ChatViewport
      lockPageScrollOnDesktop
      minBottomInset={140}
      header={
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 2,
            px: { xs: 2, md: 4 },
            py: 1.5,
            position: 'relative',
            zIndex: 5,
            bgcolor: (theme) =>
              theme.palette.mode === 'light'
                ? alpha(theme.palette.background.paper, 0.72)
                : alpha(theme.palette.background.paper, 0.58),
            backdropFilter: 'blur(18px)',
            WebkitBackdropFilter: 'blur(18px)',
            borderBottom: 1,
            borderColor: 'divider',
          }}
        >
          <FormControlLabel
            control={
              <Switch
                size='small'
                checked={allowExternal}
                onChange={(event) => setAllowExternal(event.target.checked)}
                disabled={Boolean(session)}
              />
            }
            label={
              <Typography variant='body2' color='text.secondary'>
                MCP 扩展
              </Typography>
            }
          />
          <Chip
            label={webSearchConfiguredLabel}
            size='small'
            variant='outlined'
            color={webSearch.configured ? 'success' : 'default'}
          />
          <Chip label={webSearchHealthLabel} size='small' variant='outlined' color={webSearchHealthColor} />
          <Chip label={sessionBadgeLabel} size='small' variant='outlined' />
        </Box>
      }
      renderMessages={({ bottomInset }) =>
        messages.length === 0 ? (
          <Box
            sx={{
              flex: 1,
              minHeight: 0,
              overflowY: 'auto',
              px: { xs: 2, md: 3 },
              pt: 3,
              pb: `${bottomInset}px`,
            }}
          >
            <Box
              sx={{
                minHeight: '100%',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
              }}
            >
              <WelcomeScreen
                title='你好，需要我为你做些什么？'
                suggestions={quickPrompts}
                onSuggestionClick={onSuggestionClick}
                disabled={isInputDisabled}
              />
            </Box>
          </Box>
        ) : (
          <MessageList
            messages={messages}
            loading={loading}
            onToolApprovalSubmit={onToolApprovalSubmit}
            approvalLoading={loading}
            bottomInset={bottomInset}
            scrollButtonAlign='right'
            wheelContainment='off'
          />
        )
      }
      renderComposer={({ composerRef }) => (
        <Box>
          <ErrorAlert error={error} onClose={() => setError(null)} />
          <ChatInputDock composerRef={composerRef} variant='general' maxWidth={800}>
            <InputComposer
              value={input}
              onChange={setInput}
              onSend={onSend}
              disabled={isInputDisabled}
              loading={loading}
              placeholder={hasPendingApproval ? '等待工具审批完成...' : '输入消息...'}
              showShortcutHint={false}
            />
          </ChatInputDock>
        </Box>
      )}
    />
  );
}
