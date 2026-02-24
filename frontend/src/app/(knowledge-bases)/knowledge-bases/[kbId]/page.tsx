import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RouteSWRFallbackProvider } from '@/components/providers/RouteSWRFallbackProvider';
import { prefetchKnowledgeBaseDetailRouteData } from '@/services/serverFirstRoutePrefetch';

const KnowledgeBaseDetailPage = dynamic(
  () => import('@/views/KnowledgeBaseDetailPage').then((mod) => mod.default),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default async function Page({
  params,
}: {
  params: Promise<{ kbId: string }>;
}) {
  const { kbId } = await params;
  const fallback = await prefetchKnowledgeBaseDetailRouteData(kbId);

  return (
    <RouteSWRFallbackProvider fallback={fallback}>
      <KnowledgeBaseDetailPage />
    </RouteSWRFallbackProvider>
  );
}
