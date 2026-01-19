/**
 * 代码块组件
 * 支持语法高亮、语言标签、复制按钮
 */
import { useState, useCallback } from 'react';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

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
      // 静默失败
    }
  }, [children]);

  // 语言显示名称映射
  const languageLabels: Record<string, string> = {
    javascript: 'JavaScript',
    typescript: 'TypeScript',
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

  const displayLanguage = languageLabels[language.toLowerCase()] || language.toUpperCase();

  return (
    <Box
      sx={{
        borderRadius: 3,
        overflow: 'hidden',
        bgcolor: '#282c34',
        my: 2,
      }}
    >
      {/* 代码块头部 */}
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

      {/* 代码内容 */}
      <SyntaxHighlighter
        language={language}
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
