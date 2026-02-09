import dynamic from 'next/dynamic';

const ExtensionsPage = dynamic(
  () => import('@/views/ExtensionsPage').then((mod) => mod.ExtensionsPage),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <ExtensionsPage />;
}
