import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';

const ModelConfigPage = dynamic(
  () => import('@/views/ModelConfigPage').then((mod) => mod.ModelConfigPage),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page() {
  return <ModelConfigPage />;
}
