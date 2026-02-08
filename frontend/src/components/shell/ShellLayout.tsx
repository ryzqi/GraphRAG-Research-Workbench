'use client';

import type { ReactNode } from 'react';
import { GeminiShell } from '@/components/shell/GeminiShell';

export function ShellLayout({ children }: { children: ReactNode }) {
  return <GeminiShell>{children}</GeminiShell>;
}
