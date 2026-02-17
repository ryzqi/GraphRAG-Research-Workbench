/**
 * Markdown message renderer with lazy code block highlighting.
 */
import { Suspense, lazy, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Typography, Link, Box } from '@mui/material';

const CodeBlock = lazy(async () => ({
  default: (await import('./CodeBlock')).CodeBlock,
}));

interface MarkdownContentProps {
  content: string;
  isStreaming?: boolean;
  onCitationClick?: (citationId: string) => void;
}

const INLINE_CITATION_RE = /\[S([1-9]\d*)\]/gi;
const CITATION_LINK_RE = /^#cite-(S[1-9]\d*)$/i;

type MarkdownTreeNode = {
  type?: string;
  value?: string;
  url?: string;
  title?: string | null;
  children?: MarkdownTreeNode[];
  data?: Record<string, unknown>;
};

function splitCitationText(value: string): MarkdownTreeNode[] {
  const nodes: MarkdownTreeNode[] = [];
  let lastIndex = 0;
  INLINE_CITATION_RE.lastIndex = 0;

  for (const match of value.matchAll(INLINE_CITATION_RE)) {
    const raw = match[0];
    const start = match.index ?? 0;
    const citationId = `S${match[1]}`;
    if (start > lastIndex) {
      nodes.push({ type: 'text', value: value.slice(lastIndex, start) });
    }
    nodes.push({
      type: 'link',
      url: `#cite-${citationId}`,
      title: null,
      children: [{ type: 'text', value: raw }],
      data: { citationId },
    });
    lastIndex = start + raw.length;
  }

  if (lastIndex < value.length) {
    nodes.push({ type: 'text', value: value.slice(lastIndex) });
  }

  if (nodes.length === 0) {
    return [{ type: 'text', value }];
  }
  return nodes;
}

function linkifyCitationNodes(node: MarkdownTreeNode): void {
  if (!Array.isArray(node.children) || node.children.length === 0) {
    return;
  }
  if (node.type === 'link' || node.type === 'inlineCode' || node.type === 'code') {
    return;
  }

  const transformed: MarkdownTreeNode[] = [];
  for (const child of node.children) {
    if (child.type === 'text' && typeof child.value === 'string' && child.value.includes('[S')) {
      transformed.push(...splitCitationText(child.value));
      continue;
    }
    transformed.push(child);
    linkifyCitationNodes(child);
  }
  node.children = transformed;
}

function citationLinkPlugin() {
  return (tree: MarkdownTreeNode) => {
    linkifyCitationNodes(tree);
  };
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

export function MarkdownContent({
  content,
  isStreaming = false,
  onCitationClick,
}: MarkdownContentProps) {
  const { safeContent, pendingContent } = isStreaming
    ? splitUnclosedFence(content)
    : { safeContent: content, pendingContent: '' };

  const remarkPlugins = useMemo(() => [remarkGfm, citationLinkPlugin], []);

  const markdownComponents = useMemo(
    () => ({
      p: ({ children }: { children?: React.ReactNode }) => (
        <Typography variant="body1" sx={{ mb: 1.5, lineHeight: 1.7, '&:last-child': { mb: 0 } }}>
          {children}
        </Typography>
      ),
      h1: ({ children }: { children?: React.ReactNode }) => (
        <Typography variant="h5" fontWeight={600} sx={{ mt: 3, mb: 1.5 }}>
          {children}
        </Typography>
      ),
      h2: ({ children }: { children?: React.ReactNode }) => (
        <Typography variant="h6" fontWeight={600} sx={{ mt: 2.5, mb: 1 }}>
          {children}
        </Typography>
      ),
      h3: ({ children }: { children?: React.ReactNode }) => (
        <Typography variant="subtitle1" fontWeight={600} sx={{ mt: 2, mb: 1 }}>
          {children}
        </Typography>
      ),
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
        (() => {
          const citationMatch = typeof href === 'string' ? href.match(CITATION_LINK_RE) : null;
          if (citationMatch) {
            const citationId = citationMatch[1].toUpperCase();
            return (
              <Link
                href={href}
                underline="always"
                sx={{ fontWeight: 600 }}
                onClick={(event) => {
                  event.preventDefault();
                  onCitationClick?.(citationId);
                }}
              >
                {children}
              </Link>
            );
          }
          return (
            <Link href={href} target="_blank" rel="noopener noreferrer" underline="hover">
              {children}
            </Link>
          );
        })()
      ),
      code: ({ className, children }: { className?: string; children?: React.ReactNode }) => {
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

        const code = String(children ?? '').replace(/\n$/, '');

        return (
          <Suspense
            fallback={
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
                {code}
              </Box>
            }
          >
            <CodeBlock language={match?.[1] || 'text'}>{code}</CodeBlock>
          </Suspense>
        );
      },
      pre: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
      ul: ({ children }: { children?: React.ReactNode }) => (
        <Box component="ul" sx={{ pl: 3, my: 1.5 }}>
          {children}
        </Box>
      ),
      ol: ({ children }: { children?: React.ReactNode }) => (
        <Box component="ol" sx={{ pl: 3, my: 1.5 }}>
          {children}
        </Box>
      ),
      li: ({ children }: { children?: React.ReactNode }) => (
        <Typography component="li" variant="body1" sx={{ mb: 0.5, lineHeight: 1.7 }}>
          {children}
        </Typography>
      ),
      blockquote: ({ children }: { children?: React.ReactNode }) => (
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
      table: ({ children }: { children?: React.ReactNode }) => (
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
      thead: ({ children }: { children?: React.ReactNode }) => (
        <Box component="thead" sx={{ bgcolor: 'action.hover' }}>
          {children}
        </Box>
      ),
      tbody: ({ children }: { children?: React.ReactNode }) => <tbody>{children}</tbody>,
      tr: ({ children }: { children?: React.ReactNode }) => (
        <Box component="tr" sx={{ borderBottom: 1, borderColor: 'divider' }}>
          {children}
        </Box>
      ),
      th: ({ children }: { children?: React.ReactNode }) => (
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
      td: ({ children }: { children?: React.ReactNode }) => (
        <Box component="td" sx={{ p: 1.5, textAlign: 'left' }}>
          {children}
        </Box>
      ),
      strong: ({ children }: { children?: React.ReactNode }) => (
        <Typography component="strong" fontWeight={600}>
          {children}
        </Typography>
      ),
      em: ({ children }: { children?: React.ReactNode }) => (
        <Typography component="em" sx={{ fontStyle: 'italic' }}>
          {children}
        </Typography>
      ),
    }),
    [onCitationClick]
  );

  if (!safeContent && !pendingContent) {
    return null;
  }

  return (
    <>
      {safeContent && (
        <ReactMarkdown remarkPlugins={remarkPlugins} components={markdownComponents}>
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
