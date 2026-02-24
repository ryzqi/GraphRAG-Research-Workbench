import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';

const ExtensionsPage = dynamic(
  () => import('@/views/ExtensionsPage').then((mod) => mod.ExtensionsPage),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page() {
  return <ExtensionsPage />;
}
