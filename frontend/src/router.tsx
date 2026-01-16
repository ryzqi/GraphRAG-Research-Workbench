import { Suspense, lazy } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { Layout } from './components/Layout';

// 提取静态 JSX，避免每个路由重复创建 element（Vercel rendering-hoist-jsx）
const routeFallback = <div style={{ padding: 24 }}>加载中...</div>;

const HomePage = lazy(async () => ({
  default: (await import('./pages/HomePage')).HomePage,
}));

const KbChatPage = lazy(async () => ({
  default: (await import('./pages/KbChatPage')).KbChatPage,
}));

const GeneralChatPage = lazy(async () => ({
  default: (await import('./pages/GeneralChatPage')).GeneralChatPage,
}));

const ResearchPage = lazy(async () => ({
  default: (await import('./pages/ResearchPage')).ResearchPage,
}));

const EvaluationsPage = lazy(async () => ({
  default: (await import('./pages/EvaluationsPage')).EvaluationsPage,
}));

const FeedbackPage = lazy(async () => ({
  default: (await import('./pages/FeedbackPage')).FeedbackPage,
}));

const KnowledgeBasesPage = lazy(() => import('./pages/KnowledgeBasesPage'));

const KnowledgeBaseDetailPage = lazy(() => import('./pages/KnowledgeBaseDetailPage'));

const ExtensionsPage = lazy(() => import('./pages/ExtensionsPage'));

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={routeFallback}>
            <HomePage />
          </Suspense>
        ),
      },
      {
        path: 'kb-chat',
        element: (
          <Suspense fallback={routeFallback}>
            <KbChatPage />
          </Suspense>
        ),
      },
      {
        path: 'general-chat',
        element: (
          <Suspense fallback={routeFallback}>
            <GeneralChatPage />
          </Suspense>
        ),
      },
      {
        path: 'research',
        element: (
          <Suspense fallback={routeFallback}>
            <ResearchPage />
          </Suspense>
        ),
      },
      {
        path: 'knowledge-bases',
        element: (
          <Suspense fallback={routeFallback}>
            <KnowledgeBasesPage />
          </Suspense>
        ),
      },
      {
        path: 'knowledge-bases/:kbId',
        element: (
          <Suspense fallback={routeFallback}>
            <KnowledgeBaseDetailPage />
          </Suspense>
        ),
      },
      {
        path: 'extensions',
        element: (
          <Suspense fallback={routeFallback}>
            <ExtensionsPage />
          </Suspense>
        ),
      },
      {
        path: 'evaluations',
        element: (
          <Suspense fallback={routeFallback}>
            <EvaluationsPage />
          </Suspense>
        ),
      },
      {
        path: 'feedback',
        element: (
          <Suspense fallback={routeFallback}>
            <FeedbackPage />
          </Suspense>
        ),
      },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
