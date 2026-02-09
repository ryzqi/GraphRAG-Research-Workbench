import dynamic from 'next/dynamic';

const KnowledgeBasesPage = dynamic(
  () => import('@/views/KnowledgeBasesPage').then((mod) => mod.default),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <KnowledgeBasesPage />;
}
