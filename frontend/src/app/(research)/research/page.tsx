import dynamic from 'next/dynamic';

const ResearchPage = dynamic(
  () => import('@/views/ResearchPage').then((mod) => mod.ResearchPage),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <ResearchPage />;
}
