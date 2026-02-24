import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RouteSWRFallbackProvider } from '@/components/providers/RouteSWRFallbackProvider';
import { prefetchGeneralChatRouteData } from '@/services/serverFirstRoutePrefetch';

const GeneralChatPage = dynamic(
  () => import('@/views/GeneralChatPage').then((mod) => mod.GeneralChatPage),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default async function Page() {
  const fallback = await prefetchGeneralChatRouteData();

  return (
    <RouteSWRFallbackProvider fallback={fallback}>
      <GeneralChatPage />
    </RouteSWRFallbackProvider>
  );
}
