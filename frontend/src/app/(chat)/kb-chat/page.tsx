import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RouteSWRFallbackProvider } from '@/components/providers/RouteSWRFallbackProvider';
import { prefetchKbChatRouteData } from '@/services/serverFirstRoutePrefetch';

const KbChatPage = dynamic(
  () => import('@/views/KbChatPage').then((mod) => mod.KbChatPage),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default async function Page() {
  const fallback = await prefetchKbChatRouteData();

  return (
    <RouteSWRFallbackProvider fallback={fallback}>
      <KbChatPage />
    </RouteSWRFallbackProvider>
  );
}
