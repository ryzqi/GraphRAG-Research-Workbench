/**
 * Markdown 消息渲染组件
 * 支持 Markdown 格式化和代码块高亮
 */
import ReactMarkdown from 'react-markdown';
import { Typography, Link, Box } from '@mui/material';
import { CodeBlock } from './CodeBlock';

interface MarkdownContentProps {
  content: string;
  isStreaming?: boolean;
}

function splitUnclosedFence(content: string) {
  const fence = '```';
  const fenceCount = content.split(fence).length - 1;
  if (fenceCount === 0 || fenceCount % 2 === 0) {
    return { safeContent: content, pendingContent: '' };
  }

  const lastFenceIndex = content.lastIndexOf(fence);
  return {
    safeContent: content.slice(0, lastFenceIndex),
    pendingContent: content.slice(lastFenceIndex),
  };
}

export function MarkdownContent({ content, isStreaming = false }: MarkdownContentProps) {
  const { safeContent, pendingContent } = isStreaming
    ? splitUnclosedFence(content)
    : { safeContent: content, pendingContent: '' };

  if (!safeContent && !pendingContent) {
    return null;
  }

  return (
    <>
      {safeContent && (
        <ReactMarkdown
          components={{
        // 段落
        p: ({ children }) => (
          <Typography variant="body1" sx={{ mb: 1.5, lineHeight: 1.7, '&:last-child': { mb: 0 } }}>
            {children}
          </Typography>
        ),
        // 标题
        h1: ({ children }) => (
          <Typography variant="h5" fontWeight={600} sx={{ mt: 3, mb: 1.5 }}>
            {children}
          </Typography>
        ),
        h2: ({ children }) => (
          <Typography variant="h6" fontWeight={600} sx={{ mt: 2.5, mb: 1 }}>
            {children}
          </Typography>
        ),
        h3: ({ children }) => (
          <Typography variant="subtitle1" fontWeight={600} sx={{ mt: 2, mb: 1 }}>
            {children}
          </Typography>
        ),
        // 链接
        a: ({ href, children }) => (
          <Link href={href} target="_blank" rel="noopener noreferrer" underline="hover">
            {children}
          </Link>
        ),
        // 代码块
        code: ({ className, children }) => {
          const match = /language-(\w+)/.exec(className || '');
          const isInline = !match && !className;

          if (isInline) {
            return (
              <Box
                component="code"
                sx={{
                  px: 0.75,
                  py: 0.25,
                  borderRadius: 1,
                  bgcolor: 'action.hover',
                  fontFamily: 'monospace',
                  fontSize: '0.875em',
                }}
              >
                {children}
              </Box>
            );
          }

          return (
            <CodeBlock language={match?.[1] || 'text'}>
              {String(children).replace(/\n$/, '')}
            </CodeBlock>
          );
        },
        // 预格式化
        pre: ({ children }) => <>{children}</>,
        // 列表
        ul: ({ children }) => (
          <Box component="ul" sx={{ pl: 3, my: 1.5 }}>
            {children}
          </Box>
        ),
        ol: ({ children }) => (
          <Box component="ol" sx={{ pl: 3, my: 1.5 }}>
            {children}
          </Box>
        ),
        li: ({ children }) => (
          <Typography component="li" variant="body1" sx={{ mb: 0.5, lineHeight: 1.7 }}>
            {children}
          </Typography>
        ),
        // 引用块
        blockquote: ({ children }) => (
          <Box
            sx={{
              borderLeft: 4,
              borderColor: 'primary.main',
              pl: 2,
              py: 0.5,
              my: 2,
              bgcolor: 'action.hover',
              borderRadius: '0 8px 8px 0',
            }}
          >
            {children}
          </Box>
        ),
        // 分割线
        hr: () => (
          <Box
            component="hr"
            sx={{
              border: 'none',
              height: 1,
              bgcolor: 'divider',
              my: 3,
            }}
          />
        ),
        // 表格
        table: ({ children }) => (
          <Box sx={{ overflowX: 'auto', my: 2 }}>
            <Box
              component="table"
              sx={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '0.875rem',
              }}
            >
              {children}
            </Box>
          </Box>
        ),
        thead: ({ children }) => (
          <Box component="thead" sx={{ bgcolor: 'action.hover' }}>
            {children}
          </Box>
        ),
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => (
          <Box
            component="tr"
            sx={{ borderBottom: 1, borderColor: 'divider' }}
          >
            {children}
          </Box>
        ),
        th: ({ children }) => (
          <Box
            component="th"
            sx={{
              p: 1.5,
              textAlign: 'left',
              fontWeight: 600,
              borderBottom: 2,
              borderColor: 'divider',
            }}
          >
            {children}
          </Box>
        ),
        td: ({ children }) => (
          <Box component="td" sx={{ p: 1.5, textAlign: 'left' }}>
            {children}
          </Box>
        ),
        // 强调
        strong: ({ children }) => (
          <Typography component="strong" fontWeight={600}>
            {children}
          </Typography>
        ),
        em: ({ children }) => (
          <Typography component="em" sx={{ fontStyle: 'italic' }}>
            {children}
          </Typography>
        ),
      }}
        >
          {safeContent}
        </ReactMarkdown>
      )}
      {pendingContent && (
        <Box
          component="pre"
          sx={{
            m: 0,
            mt: 1,
            p: 1.5,
            borderRadius: 2,
            bgcolor: 'action.hover',
            fontFamily: 'monospace',
            fontSize: '0.875em',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {pendingContent}
        </Box>
      )}
    </>
  );
}
