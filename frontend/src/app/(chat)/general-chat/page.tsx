'use client';

import { Suspense } from 'react';
import { GeneralChatPage } from '@/views/GeneralChatPage';

export default function Page() {
  return (
    <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
      <GeneralChatPage />
    </Suspense>
  );
}
