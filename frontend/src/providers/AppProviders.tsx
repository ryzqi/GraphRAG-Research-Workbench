'use client';

import type { ReactNode } from 'react';
import { preconnect, prefetchDNS } from 'react-dom';
import { SWRConfig } from 'swr';
import ErrorBoundary from '@/components/ErrorBoundary';
import { defaultSWRConfig } from '@/lib/swr';
import { getApiOrigin } from '@/services/http';
import { Md3ThemeProvider } from '@/theme/ThemeProvider';

const API_ORIGIN = getApiOrigin();

export function AppProviders({ children }: { children: ReactNode }) {
  if (API_ORIGIN) {
    prefetchDNS(API_ORIGIN);
    preconnect(API_ORIGIN);
  }

  return (
    <SWRConfig value={defaultSWRConfig}>
      <Md3ThemeProvider>
        <ErrorBoundary>{children}</ErrorBoundary>
      </Md3ThemeProvider>
    </SWRConfig>
  );
}
