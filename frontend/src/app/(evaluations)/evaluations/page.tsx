import dynamic from 'next/dynamic';

const EvaluationsPage = dynamic(
  () => import('@/views/EvaluationsPage').then((mod) => mod.EvaluationsPage),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <EvaluationsPage />;
}
