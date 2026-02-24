import nextVitals from 'eslint-config-next/core-web-vitals';

const config = [
  ...nextVitals,
  {
    rules: {
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/immutability': 'off',
      'import/no-anonymous-default-export': 'off',
    },
  },
  {
    files: ['src/views/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/views/*', '../views/*', '../../views/*', '../../../views/*'],
              message: 'views 层不得相互耦合，请通过 hooks/services/components 复用能力。',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/hooks/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/views/*', '../views/*', '../../views/*', '../../../views/*'],
              message: 'hooks 层不得依赖 views 层。',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/services/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '@/views/*',
                '../views/*',
                '../../views/*',
              ],
              message: 'services 层不得依赖 views 层。',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/components/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/views/*', '../views/*', '../../views/*', '../../../views/*'],
              message: 'components 层不得依赖 views 层。',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/views/KbChatPage.tsx'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '../services/chatStreamingMetrics',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问该能力。',
            },
            {
              name: '../services/kbChatAnswerReveal',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问该能力。',
            },
            {
              name: '../services/kbChatAssistantSelection',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问该能力。',
            },
            {
              name: '../services/kbChatConfig',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问该能力。',
            },
            {
              name: '../services/kbChatStrategyAvailability',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问该能力。',
            },
            {
              name: '../services/chatStreamDeltas',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问该能力。',
            },
            {
              name: '../lib/sse',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问解析能力。',
            },
            {
              name: '../lib/deltaParser',
              message: 'KbChatPage 请通过 hooks/kbChatPageBoundary 访问增量解析能力。',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/views/KnowledgeBaseAddDocumentsPage.tsx'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '../services/bootstrapSubmissions',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/bootstrapUploadSession',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/materials',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/ingestionBatches',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/ingestionEntryErrors',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/ingestionBatchRecovery',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/http',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
            {
              name: '../services/queueHealthDiagnostics',
              message: '页面层请通过 hooks/knowledgeBaseAddDocumentsBoundary 访问该能力。',
            },
          ],
        },
      ],
    },
  },
];

export default config;
