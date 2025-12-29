import { Suspense, lazy } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { Layout } from './components/Layout';

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
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <HomePage />
          </Suspense>
        ),
      },
      {
        path: 'kb-chat',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <KbChatPage />
          </Suspense>
        ),
      },
      {
        path: 'general-chat',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <GeneralChatPage />
          </Suspense>
        ),
      },
      {
        path: 'research',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <ResearchPage />
          </Suspense>
        ),
      },
      {
        path: 'knowledge-bases',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <KnowledgeBasesPage />
          </Suspense>
        ),
      },
      {
        path: 'knowledge-bases/:kbId',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <KnowledgeBaseDetailPage />
          </Suspense>
        ),
      },
      {
        path: 'extensions',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <ExtensionsPage />
          </Suspense>
        ),
      },
      {
        path: 'evaluations',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <EvaluationsPage />
          </Suspense>
        ),
      },
      {
        path: 'feedback',
        element: (
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
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
