import dynamic from 'next/dynamic';

const KnowledgeBaseAddDocumentsPage = dynamic(
  () => import('@/views/KnowledgeBaseAddDocumentsPage').then((mod) => mod.default),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <KnowledgeBaseAddDocumentsPage />;
}
