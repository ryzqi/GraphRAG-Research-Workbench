import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { RoutePrefetchBoundary } from '@/components/providers/RoutePrefetchBoundary';
import { createGeneralChatFallbackPromise } from '@/services/routePrefetch';

const GeneralChatPage = dynamic(
  () => import('@/views/GeneralChatPage').then((mod) => mod.GeneralChatPage),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page() {
  const fallbackPromise = createGeneralChatFallbackPromise();

  return (
    <RoutePrefetchBoundary fallbackPromise={fallbackPromise}>
      <GeneralChatPage />
    </RoutePrefetchBoundary>
  );
}
