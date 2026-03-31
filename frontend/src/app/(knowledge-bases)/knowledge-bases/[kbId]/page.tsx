import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RoutePrefetchBoundary } from '@/components/providers/RoutePrefetchBoundary';
import { createKnowledgeBaseDetailFallbackPromise } from '@/services/routePrefetch';

const KnowledgeBaseDetailPage = dynamic(
  () => import('@/views/KnowledgeBaseDetailPage').then((mod) => mod.default),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page({
  params,
}: {
  params: Promise<{ kbId: string }>;
}) {
  const fallbackPromise = createKnowledgeBaseDetailFallbackPromise(params);

  return (
    <RoutePrefetchBoundary fallbackPromise={fallbackPromise}>
      <KnowledgeBaseDetailPage />
    </RoutePrefetchBoundary>
  );
}
