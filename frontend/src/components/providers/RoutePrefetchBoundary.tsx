import { Suspense, use, type ReactNode } from 'react';
import type { SWRFallback } from '@/lib/swrFallback';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RouteSWRFallbackProvider } from './RouteSWRFallbackProvider';

interface RoutePrefetchBoundaryProps {
  fallbackPromise: Promise<SWRFallback>;
  children: ReactNode;
  loadingText?: string;
  loadingAriaLabel?: string;
}

function ResolvedRoutePrefetchBoundary({
  fallbackPromise,
  children,
}: Pick<RoutePrefetchBoundaryProps, 'fallbackPromise' | 'children'>) {
  const fallback = use(fallbackPromise);

  return <RouteSWRFallbackProvider fallback={fallback}>{children}</RouteSWRFallbackProvider>;
}

export function RoutePrefetchBoundary({
  fallbackPromise,
  children,
  loadingText = '加载页面...',
  loadingAriaLabel = '页面加载中',
}: RoutePrefetchBoundaryProps) {
  return (
    <Suspense
      fallback={<LoadingSpinner fullPage text={loadingText} ariaLabel={loadingAriaLabel} />}
    >
      <ResolvedRoutePrefetchBoundary fallbackPromise={fallbackPromise}>
        {children}
      </ResolvedRoutePrefetchBoundary>
    </Suspense>
  );
}
