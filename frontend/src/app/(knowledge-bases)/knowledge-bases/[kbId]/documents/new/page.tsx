import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RouteSWRFallbackProvider } from '@/components/providers/RouteSWRFallbackProvider';
import { prefetchKnowledgeBaseAddDocumentsRouteData } from '@/services/serverFirstRoutePrefetch';

const KnowledgeBaseAddDocumentsPage = dynamic(
  () => import('@/views/KnowledgeBaseAddDocumentsPage').then((mod) => mod.default),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ kbId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { kbId } = await params;
  const resolvedSearchParams = await searchParams;
  const jobParam = resolvedSearchParams.job;
  const jobId = Array.isArray(jobParam) ? jobParam[0] : jobParam;
  const fallback = await prefetchKnowledgeBaseAddDocumentsRouteData(kbId, jobId);

  return (
    <RouteSWRFallbackProvider fallback={fallback}>
      <KnowledgeBaseAddDocumentsPage />
    </RouteSWRFallbackProvider>
  );
}
