/**
 * Markdown 消息渲染组件
 * 支持 Markdown 格式化和代码块高亮
 */
import ReactMarkdown from 'react-markdown';
import { Typography, Link, Box } from '@mui/material';
import { CodeBlock } from './CodeBlock';

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
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
      {content}
    </ReactMarkdown>
  );
}
