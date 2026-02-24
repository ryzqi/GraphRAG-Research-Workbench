import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();

const iconButtonFiles = [
  'src/components/chat/CodeBlock.tsx',
  'src/components/chat/InputComposer.tsx',
  'src/components/chat/KbChatFlowPanel.tsx',
  'src/components/chat/MessageItem.tsx',
  'src/components/chat/MessageList.tsx',
  'src/components/IngestionManifestEditor.tsx',
  'src/components/Nav.tsx',
  'src/components/shell/GeminiShell.tsx',
  'src/components/shell/Sidebar.tsx',
  'src/components/ui/Modal.tsx',
  'src/views/KnowledgeBasesPage.tsx',
  'src/views/ModelConfigPage.tsx',
];

const noHexColorFiles = [
  'src/components/Nav.tsx',
  'src/components/shell/Sidebar.tsx',
];

const failures = [];

for (const file of iconButtonFiles) {
  const abs = path.join(ROOT, file);
  const content = fs.readFileSync(abs, 'utf8');
  const lines = content.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    if (!lines[i].includes('<IconButton')) {
      continue;
    }
    let snippet = lines[i];
    let j = i;
    while (j < lines.length && !/\/?>\s*$/.test(lines[j])) {
      j += 1;
      if (j < lines.length) {
        snippet += `\n${lines[j]}`;
      }
    }
    if (!snippet.includes('aria-label=')) {
      failures.push(`${file}:${i + 1} IconButton 缺少 aria-label`);
    }
  }
}

for (const file of noHexColorFiles) {
  const abs = path.join(ROOT, file);
  const content = fs.readFileSync(abs, 'utf8');
  const hexMatches = content.match(/#[0-9A-Fa-f]{3,8}/g) ?? [];
  if (hexMatches.length > 0) {
    failures.push(`${file}: 检测到硬编码颜色 ${Array.from(new Set(hexMatches)).join(', ')}`);
  }
}

if (failures.length > 0) {
  console.error('A11y/theme baseline check failed:');
  for (const item of failures) {
    console.error(`- ${item}`);
  }
  process.exit(1);
}

console.log('A11y/theme baseline check passed.');
