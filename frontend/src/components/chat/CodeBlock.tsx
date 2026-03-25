/**
 * 代码块组件
 * 轻量语法高亮 + 复制按钮
 */
import { useState, useCallback } from 'react';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import js from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import ts from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

SyntaxHighlighter.registerLanguage('javascript', js);
SyntaxHighlighter.registerLanguage('typescript', ts);
SyntaxHighlighter.registerLanguage('tsx', tsx);
SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('shell', bash);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('yaml', yaml);
SyntaxHighlighter.registerLanguage('sql', sql);
SyntaxHighlighter.registerLanguage('markdown', markdown);
SyntaxHighlighter.registerLanguage('jsx', jsx);

interface CodeBlockProps {
  language?: string;
  children: string;
}

export function CodeBlock({ language = 'text', children }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(children);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 复制失败时静默忽略。
    }
  }, [children]);

  const languageLabels: Record<string, string> = {
    javascript: 'JavaScript',
    typescript: 'TypeScript',
    tsx: 'TSX',
    python: 'Python',
    java: 'Java',
    cpp: 'C++',
    csharp: 'C#',
    go: 'Go',
    rust: 'Rust',
    sql: 'SQL',
    bash: 'Bash',
    shell: 'Shell',
    json: 'JSON',
    yaml: 'YAML',
    xml: 'XML',
    html: 'HTML',
    css: 'CSS',
    markdown: 'Markdown',
    text: 'Text',
  };

  const normalizedLanguage = language.toLowerCase();
  const displayLanguage = languageLabels[normalizedLanguage] ?? language.toUpperCase();

  return (
    <Box
      sx={{
        borderRadius: 3,
        overflow: 'hidden',
        bgcolor: '#282c34',
        my: 2,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1,
          bgcolor: '#21252b',
          borderBottom: '1px solid #373b41',
        }}
      >
        <Typography
          variant="caption"
          sx={{
            color: '#abb2bf',
            fontFamily: 'monospace',
            fontWeight: 500,
          }}
        >
          {displayLanguage}
        </Typography>
        <Tooltip title={copied ? '已复制' : '复制代码'}>
          <IconButton
            size="small"
            onClick={handleCopy}
            aria-label={copied ? '已复制代码' : '复制代码'}
            sx={{
              color: copied ? '#98c379' : '#abb2bf',
              '&:hover': {
                color: '#61afef',
                bgcolor: 'rgba(255,255,255,0.05)',
              },
            }}
          >
            {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>

      <SyntaxHighlighter
        language={normalizedLanguage}
        style={oneDark}
        customStyle={{
          margin: 0,
          padding: '16px',
          fontSize: '13px',
          lineHeight: 1.6,
          background: 'transparent',
        }}
        showLineNumbers={children.split('\n').length > 3}
        lineNumberStyle={{
          color: '#4b5263',
          minWidth: '2.5em',
          paddingRight: '1em',
        }}
      >
        {children}
      </SyntaxHighlighter>
    </Box>
  );
}
