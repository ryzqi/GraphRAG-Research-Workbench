import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
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
});
