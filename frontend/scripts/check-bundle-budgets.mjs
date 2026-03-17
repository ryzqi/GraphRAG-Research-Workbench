import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();
const NEXT_DIR = path.join(ROOT, '.next');
const CONFIG_PATH = path.join(ROOT, 'config', 'bundle-budgets.json');
const REPORT_PATH = path.join(ROOT, 'reports', 'bundle-budget-report.json');

// These budgets are repo-specific regression guardrails based on built route bundles.
// They are not Next.js defaults and should be tuned against measured output, not copied
// as generic web-performance targets.

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function fileSize(filePath) {
  return fs.statSync(filePath).size;
}

function collectRouteFiles(routeConfig) {
  const routeDir = path.join(NEXT_DIR, 'server', 'app', ...routeConfig.pageManifestDir, 'page');
  const buildManifest = readJson(path.join(routeDir, 'build-manifest.json'));
  const reactLoadableManifest = readJson(path.join(routeDir, 'react-loadable-manifest.json'));

  const files = new Set([
    ...(buildManifest.polyfillFiles ?? []),
    ...(buildManifest.rootMainFiles ?? []),
  ]);

  for (const chunk of Object.values(reactLoadableManifest)) {
    for (const file of chunk.files ?? []) {
      files.add(file);
    }
  }

  return Array.from(files).sort();
}

function toKiB(bytes) {
  return Math.round((bytes / 1024) * 10) / 10;
}

const config = readJson(CONFIG_PATH);
const report = {
  generatedAt: new Date().toISOString(),
  routes: {},
};

const failures = [];

for (const routeConfig of config.routes) {
  const files = collectRouteFiles(routeConfig);
  const totalBytes = files.reduce((sum, file) => sum + fileSize(path.join(NEXT_DIR, file)), 0);
  const budgetBytes = routeConfig.budgetBytes;
  const overBudget = totalBytes > budgetBytes;
  report.routes[routeConfig.route] = {
    totalBytes,
    totalKiB: toKiB(totalBytes),
    budgetBytes,
    budgetKiB: toKiB(budgetBytes),
    overBudget,
    files,
  };
  if (overBudget) {
    failures.push(
      `${routeConfig.route}: ${toKiB(totalBytes)} KiB > budget ${toKiB(budgetBytes)} KiB`
    );
  }
}

fs.mkdirSync(path.dirname(REPORT_PATH), { recursive: true });
fs.writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

if (failures.length > 0) {
  console.error('Bundle budget check failed:');
  for (const line of failures) {
    console.error(`- ${line}`);
  }
  process.exit(1);
}

console.log('Bundle budget check passed.');
