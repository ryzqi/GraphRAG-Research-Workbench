import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const ROOT = process.cwd();
const SRC_DIR = path.join(ROOT, 'src');
const EXEMPTIONS_FILE = path.join(ROOT, 'config', 'line-limit-exemptions.json');
const MAX_LINES = 500;

function walkFiles(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const result = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      result.push(...walkFiles(fullPath));
      continue;
    }
    if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name)) {
      result.push(fullPath);
    }
  }
  return result;
}

function normalizeRelative(filePath) {
  return path.relative(ROOT, filePath).replace(/\\/g, '/');
}

function countLines(filePath) {
  const content = readFileSync(filePath, 'utf8');
  if (!content) {
    return 0;
  }
  return content.split(/\r?\n/).length;
}

const exemptions = JSON.parse(readFileSync(EXEMPTIONS_FILE, 'utf8'));
const today = new Date().toISOString().slice(0, 10);
const exemptionByPath = new Map(
  exemptions.map((item) => [
    item.path,
    {
      ...item,
      expiresOn: item.expiresOn,
      maxLines: Number(item.maxLines ?? MAX_LINES),
    },
  ])
);

const violations = [];
const expiredExemptions = [];
const files = walkFiles(SRC_DIR);

for (const file of files) {
  const rel = normalizeRelative(file);
  const lineCount = countLines(file);
  if (lineCount <= MAX_LINES) {
    continue;
  }

  const exemption = exemptionByPath.get(rel);
  if (!exemption) {
    violations.push({ path: rel, lineCount, reason: 'missing_exemption' });
    continue;
  }

  if (exemption.expiresOn < today) {
    expiredExemptions.push({ path: rel, lineCount, expiresOn: exemption.expiresOn });
    continue;
  }

  if (lineCount > exemption.maxLines) {
    violations.push({
      path: rel,
      lineCount,
      reason: `exemption_limit_exceeded(${exemption.maxLines})`,
    });
  }
}

for (const item of exemptions) {
  const filePath = path.join(ROOT, item.path);
  if (!statSync(filePath, { throwIfNoEntry: false })) {
    violations.push({
      path: item.path,
      lineCount: 0,
      reason: 'exemption_points_to_missing_file',
    });
  }
}

if (expiredExemptions.length > 0) {
  console.error('Found expired line-limit exemptions:');
  for (const item of expiredExemptions) {
    console.error(`- ${item.path} (${item.lineCount} lines), expired ${item.expiresOn}`);
  }
}

if (violations.length > 0) {
  console.error(`Line limit check failed (max ${MAX_LINES} lines).`);
  for (const item of violations) {
    console.error(`- ${item.path}: ${item.lineCount} (${item.reason})`);
  }
  process.exit(1);
}

console.log(`Line limit check passed (${files.length} files scanned, max ${MAX_LINES} lines).`);
