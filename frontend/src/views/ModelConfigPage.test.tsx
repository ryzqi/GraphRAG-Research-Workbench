import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ModelConfigRead } from '../services/modelConfig';

const reactState = vi.hoisted(() => ({
  sequence: [] as Array<[unknown, (value: unknown) => void]>,
  index: 0,
}));

type ButtonProps = {
  children?: unknown;
  onClick?: () => void;
};

const renderedButtons = vi.hoisted(() => [] as Array<ButtonProps>);

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useState: <T,>(initialState: T) => {
      const next = reactState.sequence[reactState.index] as [T, (value: T) => void] | undefined;
      reactState.index += 1;
      return next ?? actual.useState(initialState);
    },
  };
});

function createBaseConfig(): ModelConfigRead {
  return {
    providers: [
      {
        provider: 'openai',
        enabled: true,
        base_url: 'https://api.openai.com/v1',
        models: ['gpt-4o-mini'],
        thinking_enabled: true,
        thinking_level: 'high',
        api_key_set: true,
        api_key_masked: 'sk-***',
        updated_at: '2026-04-07T10:00:00Z',
      },
      {
        provider: 'ollama',
        enabled: false,
        base_url: 'http://127.0.0.1:11434',
        models: ['qwen3:8b'],
        thinking_enabled: true,
        thinking_level: 'high',
        api_key_set: false,
        api_key_masked: null,
        updated_at: '2026-04-07T10:00:00Z',
      },
      {
        provider: 'nvidia',
        enabled: false,
        base_url: null,
        models: ['nvidia/llama-3.1-nemotron-nano-vl-8b-v1'],
        thinking_enabled: true,
        thinking_level: null,
        api_key_set: false,
        api_key_masked: null,
        updated_at: '2026-04-07T10:00:00Z',
      },
      {
        provider: 'anthropic',
        enabled: false,
        base_url: 'http://example',
        models: ['claude-sonnet-4-6'],
        thinking_enabled: true,
        thinking_level: 'high',
        api_key_set: false,
        api_key_masked: null,
        updated_at: '2026-04-07T10:00:00Z',
      },
    ],
    active_provider: 'openai',
    active_model: 'gpt-4o-mini',
    updated_at: '2026-04-07T10:00:00Z',
  };
}

const queryState = vi.hoisted(
  (): { config: ModelConfigRead } => ({
    config: createBaseConfig(),
  })
);

const updateProviderMutateAsyncMock = vi.fn();
const updateProviderResetMock = vi.fn();
const updateActiveMutateMock = vi.fn();
const updateActiveResetMock = vi.fn();
const refetchMock = vi.fn();

vi.mock('../hooks/queries/useModelConfig', () => ({
  useModelConfig: () => ({
    data: queryState.config,
    error: null,
    isPending: false,
    refetch: refetchMock,
  }),
  useUpdateProviderConfig: () => ({
    isPending: false,
    error: null,
    mutateAsync: updateProviderMutateAsyncMock,
    reset: updateProviderResetMock,
  }),
  useUpdateActiveModel: () => ({
    isPending: false,
    error: null,
    mutate: updateActiveMutateMock,
    reset: updateActiveResetMock,
  }),
}));

vi.mock('../components/ui/Button', () => ({
  Button: (props: ButtonProps) => {
    renderedButtons.push(props);
    return null;
  },
}));

import { ModelConfigPage } from './ModelConfigPage';

function flattenChildren(children: unknown): string {
  if (typeof children === 'string') {
    return children;
  }
  if (Array.isArray(children)) {
    return children.map(flattenChildren).join('');
  }
  return '';
}

function findButton(label: string) {
  return renderedButtons.find((props) => flattenChildren(props.children) === label);
}

function primeState(selectedProvider: 'openai' | 'anthropic' = 'openai') {
  const setForms = vi.fn();
  const setSelectedProvider = vi.fn();
  const setActiveProviderDraft = vi.fn();
  const setActiveModelDraft = vi.fn();
  const setPageError = vi.fn();
  const setPendingProviderAction = vi.fn();
  const setDraggingModel = vi.fn();

  reactState.sequence = [
    [
      {
        openai: {
          enabled: true,
          baseUrl: 'https://api.openai.com/v1',
          models: ['gpt-4o-mini'],
          modelInput: '',
          apiKey: '',
          clearApiKey: false,
          thinkingEnabled: true,
          thinkingLevel: 'high',
        },
        ollama: {
          enabled: false,
          baseUrl: 'http://127.0.0.1:11434',
          models: ['qwen3:8b'],
          modelInput: '',
          apiKey: '',
          clearApiKey: false,
          thinkingEnabled: true,
          thinkingLevel: 'high',
        },
        nvidia: {
          enabled: false,
          baseUrl: '',
          models: ['nvidia/llama-3.1-nemotron-nano-vl-8b-v1'],
          modelInput: '',
          apiKey: '',
          clearApiKey: false,
          thinkingEnabled: true,
          thinkingLevel: 'high',
        },
        anthropic: {
          enabled: false,
          baseUrl: 'http://example',
          models: ['claude-sonnet-4-6'],
          modelInput: '',
          apiKey: '',
          clearApiKey: false,
          thinkingEnabled: true,
          thinkingLevel: 'high',
        },
      },
      setForms,
    ],
    [selectedProvider, setSelectedProvider],
    ['openai', setActiveProviderDraft],
    ['gpt-4o-mini', setActiveModelDraft],
    [null, setPageError],
    [null, setPendingProviderAction],
    [null, setDraggingModel],
  ];
  reactState.index = 0;

  return {
    setForms,
    setPendingProviderAction,
  };
}

afterEach(() => {
  renderedButtons.length = 0;
  reactState.sequence = [];
  reactState.index = 0;
  queryState.config = createBaseConfig();
  updateProviderMutateAsyncMock.mockReset();
  updateProviderResetMock.mockReset();
  updateActiveMutateMock.mockReset();
  updateActiveResetMock.mockReset();
  refetchMock.mockReset();
});

describe('ModelConfigPage', () => {
  it('renders anthropic provider label and endpoint hint', () => {
    primeState('anthropic');

    const html = renderToStaticMarkup(<ModelConfigPage />);

    expect(html).toContain('Anthropic');
    expect(html).toContain('/v1/messages');
  });

  it('renders a dedicated clear button when the provider already has a saved API Key', () => {
    primeState();

    renderToStaticMarkup(<ModelConfigPage />);

    expect(findButton('清空已保存 API Key')).toBeDefined();
  });

  it('clears the saved API Key immediately without sending unrelated fields', async () => {
    const baseConfig = createBaseConfig();
    updateProviderMutateAsyncMock.mockResolvedValue({
      ...baseConfig,
      providers: baseConfig.providers.map((provider) =>
        provider.provider === 'openai'
          ? { ...provider, api_key_set: false, api_key_masked: null }
          : provider
      ),
    });
    const { setPendingProviderAction } = primeState();

    renderToStaticMarkup(<ModelConfigPage />);

    const clearButton = findButton('清空已保存 API Key');

    expect(clearButton).toBeDefined();

    clearButton?.onClick?.();
    await Promise.resolve();
    await Promise.resolve();

    expect(updateProviderMutateAsyncMock).toHaveBeenCalledWith({
      provider: 'openai',
      payload: { api_key: '' },
    });
    expect(setPendingProviderAction).toHaveBeenCalledWith({
      provider: 'openai',
      kind: 'clear-api-key',
    });
  });
});
