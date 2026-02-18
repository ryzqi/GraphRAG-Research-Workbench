'use client';

import SaveIcon from '@mui/icons-material/Save';
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest';
import {
  Alert,
  Box,
  Chip,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { PageHeader } from '../components/ui/PageHeader';
import {
  useModelConfig,
  useUpdateActiveModel,
  useUpdateProviderConfig,
} from '../hooks/queries/useModelConfig';
import { getErrorMessage } from '../lib/errorHandler';
import type {
  ModelConfigRead,
  ModelProvider,
  ProviderConfigRead,
  ProviderConfigUpdate,
} from '../services/modelConfig';

const PROVIDER_LABEL: Record<ModelProvider, string> = {
  openai: 'OpenAI',
  ollama: 'Ollama',
  nvidia: 'NVIDIA',
};

type ProviderFormState = {
  enabled: boolean;
  baseUrl: string;
  model: string;
  apiKey: string;
  clearApiKey: boolean;
  thinkingEnabled: boolean;
  thinkingLevel: string;
};

const EMPTY_FORM: ProviderFormState = {
  enabled: true,
  baseUrl: '',
  model: '',
  apiKey: '',
  clearApiKey: false,
  thinkingEnabled: true,
  thinkingLevel: 'high',
};

function toOptionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function buildForm(provider: ProviderConfigRead | undefined): ProviderFormState {
  if (!provider) {
    return { ...EMPTY_FORM };
  }
  return {
    enabled: provider.enabled,
    baseUrl: provider.base_url ?? '',
    model: provider.model ?? '',
    apiKey: '',
    clearApiKey: false,
    thinkingEnabled: provider.thinking_enabled,
    thinkingLevel: provider.thinking_level ?? 'high',
  };
}

function providerMap(config: ModelConfigRead | undefined): Record<ModelProvider, ProviderConfigRead | undefined> {
  const base: Record<ModelProvider, ProviderConfigRead | undefined> = {
    openai: undefined,
    ollama: undefined,
    nvidia: undefined,
  };
  if (!config) return base;
  for (const provider of config.providers) {
    base[provider.provider] = provider;
  }
  return base;
}

export function ModelConfigPage() {
  const configQuery = useModelConfig();
  const updateProviderMutation = useUpdateProviderConfig();
  const updateActiveMutation = useUpdateActiveModel();

  const [forms, setForms] = useState<Record<ModelProvider, ProviderFormState>>({
    openai: { ...EMPTY_FORM },
    ollama: { ...EMPTY_FORM },
    nvidia: { ...EMPTY_FORM },
  });
  const [activeProviderDraft, setActiveProviderDraft] = useState<ModelProvider>('openai');
  const [activeModelDraft, setActiveModelDraft] = useState('');
  const [pageError, setPageError] = useState<string | null>(null);

  const providerById = useMemo(() => providerMap(configQuery.data), [configQuery.data]);

  useEffect(() => {
    const config = configQuery.data;
    if (!config) return;
    const enabled = config.providers.filter((item) => item.enabled);
    const resolvedActiveProvider =
      enabled.find((item) => item.provider === config.active_provider)
        ?.provider ??
      enabled[0]?.provider ??
      config.active_provider;
    setForms({
      openai: buildForm(providerById.openai),
      ollama: buildForm(providerById.ollama),
      nvidia: buildForm(providerById.nvidia),
    });
    setActiveProviderDraft(resolvedActiveProvider);
    setActiveModelDraft(config.active_model ?? '');
  }, [configQuery.data, providerById.nvidia, providerById.ollama, providerById.openai]);

  const mergedError =
    pageError ??
    (configQuery.error ? getErrorMessage(configQuery.error) : null) ??
    (updateProviderMutation.error ? getErrorMessage(updateProviderMutation.error) : null) ??
    (updateActiveMutation.error ? getErrorMessage(updateActiveMutation.error) : null);

  const closeError = () => {
    if (pageError) {
      setPageError(null);
      return;
    }
    if (updateProviderMutation.error) {
      updateProviderMutation.reset();
      return;
    }
    if (updateActiveMutation.error) {
      updateActiveMutation.reset();
      return;
    }
    if (configQuery.error) {
      void configQuery.refetch();
    }
  };

  const enabledProviders = useMemo(
    () => (configQuery.data?.providers ?? []).filter((item) => item.enabled),
    [configQuery.data]
  );

  const updateForm = <K extends keyof ProviderFormState>(
    provider: ModelProvider,
    key: K,
    value: ProviderFormState[K]
  ) => {
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...prev[provider],
        [key]: value,
      },
    }));
  };

  const handleSaveProvider = (provider: ModelProvider) => {
    const form = forms[provider];
    const payload: ProviderConfigUpdate = {
      enabled: form.enabled,
      base_url: toOptionalText(form.baseUrl),
      model: toOptionalText(form.model),
      thinking_enabled: form.thinkingEnabled,
      thinking_level:
        provider === 'nvidia'
          ? null
          : toOptionalText(form.thinkingLevel) ?? 'high',
    };
    if (form.apiKey.trim()) {
      payload.api_key = form.apiKey.trim();
    } else if (form.clearApiKey) {
      payload.api_key = '';
    }

    updateProviderMutation.mutate(
      { provider, payload },
      {
        onSuccess: () => {
          setForms((prev) => ({
            ...prev,
            [provider]: {
              ...prev[provider],
              apiKey: '',
              clearApiKey: false,
            },
          }));
        },
      }
    );
  };

  const handleApplyActiveModel = () => {
    const model = toOptionalText(activeModelDraft);
    if (!model) {
      setPageError('请填写全局生效模型名');
      return;
    }
    updateActiveMutation.mutate({
      provider: activeProviderDraft,
      model,
    });
  };

  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 3 }}>
      <PageHeader
        title='模型配置'
        subtitle='仅支持 OpenAI / Ollama / NVIDIA。保存后新请求立即按全局配置生效。'
      />

      <ErrorAlert error={mergedError} onClose={closeError} sx={{ mt: 0, mb: 2 }} />

      <Paper variant='outlined' sx={{ p: 2, mb: 2 }}>
        <Stack spacing={2}>
          <Typography variant='h6'>全局生效模型</Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
            <FormControl fullWidth>
              <InputLabel id='active-provider-label'>供应商</InputLabel>
              <Select
                labelId='active-provider-label'
                label='供应商'
                value={activeProviderDraft}
                onChange={(e) => setActiveProviderDraft(e.target.value as ModelProvider)}
              >
                {enabledProviders.map((item) => (
                  <MenuItem key={item.provider} value={item.provider}>
                    {PROVIDER_LABEL[item.provider]}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label='模型名'
              placeholder='手动输入模型名'
              value={activeModelDraft}
              onChange={(e) => setActiveModelDraft(e.target.value)}
            />
            <Button
              variant='contained'
              startIcon={<SettingsSuggestIcon />}
              disabled={enabledProviders.length === 0}
              loading={updateActiveMutation.isPending}
              onClick={handleApplyActiveModel}
              sx={{ minWidth: 180 }}
            >
              应用全局模型
            </Button>
          </Stack>
          {configQuery.data && (
            <Stack direction='row' spacing={1} alignItems='center'>
              <Typography variant='body2' color='text.secondary'>
                当前生效：
              </Typography>
              <Chip
                color='primary'
                label={`${PROVIDER_LABEL[configQuery.data.active_provider]} / ${configQuery.data.active_model ?? '-'}`}
              />
            </Stack>
          )}
          {enabledProviders.length === 0 && (
            <Alert severity='warning'>当前无启用供应商，请先在下方启用至少一个供应商。</Alert>
          )}
        </Stack>
      </Paper>

      <Grid container spacing={2}>
        {(['openai', 'ollama', 'nvidia'] as const).map((provider) => {
          const row = providerById[provider];
          const form = forms[provider];
          const isActive = configQuery.data?.active_provider === provider;
          return (
            <Grid key={provider} size={{ xs: 12, lg: 4 }}>
              <Paper variant='outlined' sx={{ p: 2, height: '100%' }}>
                <Stack spacing={1.5}>
                  <Stack direction='row' justifyContent='space-between' alignItems='center'>
                    <Typography variant='h6'>{PROVIDER_LABEL[provider]}</Typography>
                    {isActive && <Chip label='全局生效中' color='success' size='small' />}
                  </Stack>

                  <FormControlLabel
                    control={
                      <Switch
                        checked={form.enabled}
                        onChange={(e) => updateForm(provider, 'enabled', e.target.checked)}
                      />
                    }
                    label='启用供应商'
                  />

                  <TextField
                    fullWidth
                    label='Base URL'
                    placeholder={provider === 'ollama' ? 'http://127.0.0.1:11434' : '可选'}
                    value={form.baseUrl}
                    onChange={(e) => updateForm(provider, 'baseUrl', e.target.value)}
                  />
                  <TextField
                    fullWidth
                    label='模型名'
                    placeholder='手动输入模型名'
                    value={form.model}
                    onChange={(e) => updateForm(provider, 'model', e.target.value)}
                  />

                  <TextField
                    fullWidth
                    label='API Key'
                    type='password'
                    placeholder={row?.api_key_masked ?? '留空表示不修改'}
                    value={form.apiKey}
                    onChange={(e) => updateForm(provider, 'apiKey', e.target.value)}
                    helperText={
                      row?.api_key_set
                        ? `已配置：${row.api_key_masked ?? '******'}`
                        : '未配置'
                    }
                  />
                  <FormControlLabel
                    control={
                      <Switch
                        checked={form.clearApiKey}
                        onChange={(e) => updateForm(provider, 'clearApiKey', e.target.checked)}
                      />
                    }
                    label='清空已保存 API Key'
                  />

                  <FormControlLabel
                    control={
                      <Switch
                        checked={form.thinkingEnabled}
                        onChange={(e) =>
                          updateForm(provider, 'thinkingEnabled', e.target.checked)
                        }
                      />
                    }
                    label='开启思考'
                  />

                  {provider !== 'nvidia' ? (
                    <FormControl fullWidth>
                      <InputLabel id={`${provider}-thinking-level-label`}>思考强度</InputLabel>
                      <Select
                        labelId={`${provider}-thinking-level-label`}
                        label='思考强度'
                        value={form.thinkingLevel || 'high'}
                        disabled={!form.thinkingEnabled}
                        onChange={(e) => updateForm(provider, 'thinkingLevel', String(e.target.value))}
                      >
                        <MenuItem value='high'>high（最高）</MenuItem>
                        <MenuItem value='medium'>medium</MenuItem>
                        <MenuItem value='low'>low</MenuItem>
                      </Select>
                    </FormControl>
                  ) : (
                    <Alert severity='info'>NVIDIA 仅支持思考开关，不支持强度分级。</Alert>
                  )}

                  <Button
                    variant='contained'
                    startIcon={<SaveIcon />}
                    loading={updateProviderMutation.isPending}
                    onClick={() => handleSaveProvider(provider)}
                  >
                    保存 {PROVIDER_LABEL[provider]}
                  </Button>
                </Stack>
              </Paper>
            </Grid>
          );
        })}
      </Grid>
    </Box>
  );
}

export default ModelConfigPage;
