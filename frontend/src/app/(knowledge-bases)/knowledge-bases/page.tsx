import dynamic from 'next/dynamic';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';

const KnowledgeBasesPage = dynamic(
  () => import('@/views/KnowledgeBasesPage').then((mod) => mod.default),
  {
    loading: () => <LoadingSpinner fullPage text='加载页面...' ariaLabel='页面加载中' />,
  }
);

export default function Page() {
  return <KnowledgeBasesPage />;
}
