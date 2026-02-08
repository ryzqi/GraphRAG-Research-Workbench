import { Suspense, lazy } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { GeminiShell } from './components/shell';

const routeFallback = <div style={{ padding: 24 }}>加载中...</div>;

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

const KnowledgeBasesPage = lazy(() => import('./pages/KnowledgeBasesPage'));
const KnowledgeBaseCreateWizardPage = lazy(() => import('./pages/KnowledgeBaseCreateWizardPage'));
const KnowledgeBaseDetailPage = lazy(() => import('./pages/KnowledgeBaseDetailPage'));
const ExtensionsPage = lazy(() => import('./pages/ExtensionsPage'));

const router = createBrowserRouter([
  {
    path: '/',
    element: <GeminiShell />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={routeFallback}>
            <GeneralChatPage />
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
        path: 'knowledge-bases/new',
        element: (
          <Suspense fallback={routeFallback}>
            <KnowledgeBaseCreateWizardPage />
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
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
