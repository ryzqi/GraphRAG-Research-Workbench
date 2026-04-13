import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(scriptPath), '..', '..');
const frontendRoot = path.join(repoRoot, 'frontend');
const srcRoot = path.join(frontendRoot, 'src');

const forbiddenTokens = ['127.0.0.1', 'localhost', 'VITE_API_BASE_URL'];
const sourceExtensions = new Set(['.ts', '.tsx']);
const issues = [];

function walk(directoryPath) {
  const entries = fs.readdirSync(directoryPath, { withFileTypes: true });
  for (const entry of entries) {
    const absolutePath = path.join(directoryPath, entry.name);
    if (entry.isDirectory()) {
      walk(absolutePath);
      continue;
    }
    if (!sourceExtensions.has(path.extname(entry.name))) {
      continue;
    }
    if (entry.name.includes('.test.') || entry.name.includes('.spec.')) {
      continue;
    }
    checkFile(absolutePath);
  }
}

function checkFile(absolutePath) {
  const source = fs.readFileSync(absolutePath, 'utf8');
  const relativePath = path.relative(repoRoot, absolutePath).replaceAll(path.sep, '/');
  for (const token of forbiddenTokens) {
    const lines = source.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (line.includes(token)) {
        issues.push(`${relativePath}:${index + 1} contains forbidden token ${token}`);
      }
    });
  }
}

checkFile(path.join(frontendRoot, 'package.json'));
walk(srcRoot);

if (issues.length > 0) {
  console.error(`[FAIL] public runtime config audit found ${issues.length} issue(s).`);
  for (const issue of issues) {
    console.error(` - ${issue}`);
  }
  process.exit(1);
}

console.log('[PASS] public runtime config audit passed.');
