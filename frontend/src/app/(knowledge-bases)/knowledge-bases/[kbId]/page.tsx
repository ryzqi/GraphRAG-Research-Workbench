import dynamic from 'next/dynamic';

const KnowledgeBaseDetailPage = dynamic(
  () => import('@/views/KnowledgeBaseDetailPage').then((mod) => mod.default),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <KnowledgeBaseDetailPage />;
}
