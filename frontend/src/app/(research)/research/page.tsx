import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';

const ResearchPage = dynamic(
  () => import('@/views/ResearchPage').then((mod) => mod.ResearchPage),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page() {
  return <ResearchPage />;
}
