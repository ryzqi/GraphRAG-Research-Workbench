import dynamic from 'next/dynamic';

const GeneralChatPage = dynamic(
  () => import('@/views/GeneralChatPage').then((mod) => mod.GeneralChatPage),
  {
    loading: () => <div style={{ padding: 24 }}>加载中...</div>,
  }
);

export default function Page() {
  return <GeneralChatPage />;
}
