import dynamic from 'next/dynamic';

const KnowledgeBaseCreateWizardPage = dynamic(
  () => import('@/views/KnowledgeBaseCreateWizardPage').then((mod) => mod.default),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <KnowledgeBaseCreateWizardPage />;
}
