import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { AppProviders } from '@/providers/AppProviders';
import { ShellLayout } from '@/components/shell/ShellLayout';
import './globals.css';

export const metadata: Metadata = {
  title: '多知识库知识代理',
  description: 'Next.js migration frontend for multi-kb agent system.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <AppProviders>
          <ShellLayout>{children}</ShellLayout>
        </AppProviders>
      </body>
    </html>
  );
}
