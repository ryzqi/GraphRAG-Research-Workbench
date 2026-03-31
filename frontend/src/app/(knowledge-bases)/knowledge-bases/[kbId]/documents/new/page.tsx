import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RoutePrefetchBoundary } from '@/components/providers/RoutePrefetchBoundary';
import { createKnowledgeBaseAddDocumentsFallbackPromise } from '@/services/routePrefetch';

const KnowledgeBaseAddDocumentsPage = dynamic(
  () => import('@/views/KnowledgeBaseAddDocumentsPage').then((mod) => mod.default),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page({
  params,
  searchParams,
}: {
  params: Promise<{ kbId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const fallbackPromise = createKnowledgeBaseAddDocumentsFallbackPromise(params, searchParams);

  return (
    <RoutePrefetchBoundary fallbackPromise={fallbackPromise}>
      <KnowledgeBaseAddDocumentsPage />
    </RoutePrefetchBoundary>
  );
}
