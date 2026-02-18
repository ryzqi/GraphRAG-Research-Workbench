import dynamic from 'next/dynamic';

const ModelConfigPage = dynamic(
  () => import('@/views/ModelConfigPage').then((mod) => mod.ModelConfigPage),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <ModelConfigPage />;
}
