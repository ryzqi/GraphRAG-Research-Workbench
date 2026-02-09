import dynamic from 'next/dynamic';

const KbChatPage = dynamic(
  () => import('@/views/KbChatPage').then((mod) => mod.KbChatPage),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <KbChatPage />;
}
