import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

function normalizeApiBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  const withoutPrefix = trimmed.replace(/\/api\/v1$/, '');
  try {
    const url = new URL(withoutPrefix);
    // Avoid IPv6 (::1) resolution issues for local dev.
    if (url.hostname === 'localhost') {
      url.hostname = '127.0.0.1';
    }
    return url.toString().replace(/\/$/, '');
  } catch {
    return withoutPrefix;
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiBaseUrl = env.VITE_API_BASE_URL || process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
  const proxyTarget = normalizeApiBaseUrl(apiBaseUrl);

  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      // Dev-only reverse proxy. This avoids CORS and also bypasses system proxy quirks in browsers
      // by keeping requests same-origin (Vite -> backend via Node).
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      // 代码分割策略
      rollupOptions: {
        output: {
          manualChunks: {
            // React 核心
            'vendor-react': ['react', 'react-dom', 'react-router-dom'],
            // MUI 组件库
            'vendor-mui': ['@mui/material', '@emotion/react', '@emotion/styled'],
            // React Query
            'vendor-query': ['@tanstack/react-query'],
          },
        },
      },
      // 压缩优化
      minify: 'esbuild',
      // 分块大小警告阈值
      chunkSizeWarningLimit: 500,
      // 不生成 sourcemap（生产环境）
      sourcemap: false,
    },
    // 依赖预构建优化
    optimizeDeps: {
      include: [
        '@mui/material',
        '@mui/icons-material',
        '@emotion/react',
        '@emotion/styled',
        '@tanstack/react-query',
      ],
    },
  };
});
