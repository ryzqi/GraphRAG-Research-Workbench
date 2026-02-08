'use client';

import { Suspense } from 'react';
import { KbChatPage } from '@/views/KbChatPage';

export default function Page() {
  return (
    <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
      <KbChatPage />
    </Suspense>
  );
}
