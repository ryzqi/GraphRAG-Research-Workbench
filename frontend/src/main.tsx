import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import ErrorBoundary from './components/ErrorBoundary';
import { AppRouter } from './router';
import { Md3ThemeProvider } from './theme/ThemeProvider';
import { queryClient } from './lib/queryClient';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Md3ThemeProvider>
        <ErrorBoundary>
          <AppRouter />
        </ErrorBoundary>
      </Md3ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
