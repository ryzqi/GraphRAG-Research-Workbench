'use client';

import type { ReactNode } from 'react';
import { SWRConfig } from 'swr';
import ErrorBoundary from '@/components/ErrorBoundary';
import { defaultSWRConfig } from '@/lib/swr';
import { Md3ThemeProvider } from '@/theme/ThemeProvider';

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={defaultSWRConfig}>
      <Md3ThemeProvider>
        <ErrorBoundary>{children}</ErrorBoundary>
      </Md3ThemeProvider>
    </SWRConfig>
  );
}
