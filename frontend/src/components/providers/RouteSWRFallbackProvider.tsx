'use client';

import type { ReactNode } from 'react';
import { SWRConfig } from 'swr';
import type { SWRFallback } from '@/lib/swrFallback';

interface RouteSWRFallbackProviderProps {
  fallback: SWRFallback;
  children: ReactNode;
}

export function RouteSWRFallbackProvider({ fallback, children }: RouteSWRFallbackProviderProps) {
  return <SWRConfig value={{ fallback }}>{children}</SWRConfig>;
}
