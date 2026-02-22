'use client';

import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import SaveIcon from '@mui/icons-material/Save';
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest';
import {
  Alert,
  Box,
  Chip,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import { useEffect, useMemo, useState, type DragEvent, type KeyboardEvent } from 'react';

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

const PROVIDERS = ['openai', 'ollama', 'nvidia'] as const;

const PROVIDER_LABEL: Record<ModelProvider, string> = {
  openai: 'OpenAI',
  ollama: 'Ollama',
  nvidia: 'NVIDIA',
};

type ProviderFormState = {
  enabled: boolean;
  baseUrl: string;
  models: string[];
  modelInput: string;
  apiKey: string;
  clearApiKey: boolean;
  thinkingEnabled: boolean;
  thinkingLevel: string;
};

type DraggingModelState = {
  provider: ModelProvider;
  index: number;
} | null;

const EMPTY_FORM: ProviderFormState = {
  enabled: true,
  baseUrl: '',
  models: [],
  modelInput: '',
  apiKey: '',
  clearApiKey: false,
  thinkingEnabled: true,
  thinkingLevel: 'high',
};

function normalizeModelNames(values: string[]): string[] {
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const raw of values) {
    const value = raw.trim();
    if (!value || seen.has(value)) {
      continue;
    }
    deduped.push(value);
    seen.add(value);
  }
  return deduped;
}

function toOptionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function moveModel(models: string[], from: number, to: number): string[] {
  if (from === to || from < 0 || to < 0 || from >= models.length || to >= models.length) {
    return models;
  }
  const next = [...models];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

function buildForm(provider: ProviderConfigRead | undefined): ProviderFormState {
  if (!provider) {
    return { ...EMPTY_FORM };
  }
  return {
    enabled: provider.enabled,
    baseUrl: provider.base_url ?? '',
    models: normalizeModelNames(provider.models ?? []),
    modelInput: '',
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
  if (!config) {
    return base;
  }
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
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider>('openai');
  const [activeProviderDraft, setActiveProviderDraft] = useState<ModelProvider>('openai');
  const [activeModelDraft, setActiveModelDraft] = useState('');
  const [pageError, setPageError] = useState<string | null>(null);
  const [savingProvider, setSavingProvider] = useState<ModelProvider | null>(null);
  const [draggingModel, setDraggingModel] = useState<DraggingModelState>(null);

  const providerById = useMemo(() => providerMap(configQuery.data), [configQuery.data]);
  const selectedProviderForm = forms[selectedProvider];
  const selectedProviderPersisted = providerById[selectedProvider];

  useEffect(() => {
    const config = configQuery.data;
    if (!config) {
      return;
    }
    const providerLookup = providerMap(config);
    setForms({
      openai: buildForm(providerLookup.openai),
      ollama: buildForm(providerLookup.ollama),
      nvidia: buildForm(providerLookup.nvidia),
    });
    setSelectedProvider(config.active_provider);
    setActiveProviderDraft(config.active_provider);
    setActiveModelDraft(config.active_model ?? '');
  }, [configQuery.data]);

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

  const enabledProviderIds = useMemo(
    () => PROVIDERS.filter((provider) => providerById[provider]?.enabled),
    [providerById]
  );

  useEffect(() => {
    if (enabledProviderIds.length === 0) {
      return;
    }
    if (!enabledProviderIds.includes(activeProviderDraft)) {
      setActiveProviderDraft(enabledProviderIds[0]);
    }
  }, [activeProviderDraft, enabledProviderIds]);

  const activeProviderModels = useMemo(
    () => providerById[activeProviderDraft]?.models ?? [],
    [activeProviderDraft, providerById]
  );

  useEffect(() => {
    if (activeProviderModels.length === 0) {
      if (activeModelDraft) {
        setActiveModelDraft('');
      }
      return;
    }
    if (!activeProviderModels.includes(activeModelDraft)) {
      setActiveModelDraft(activeProviderModels[0]);
    }
  }, [activeModelDraft, activeProviderModels]);

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

  const addProviderModel = (provider: ModelProvider) => {
    const form = forms[provider];
    const candidate = form.modelInput.trim();
    if (!candidate) {
      return;
    }
    const models = normalizeModelNames([...form.models, candidate]);
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...prev[provider],
        models,
        modelInput: '',
      },
    }));
  };

  const removeProviderModel = (provider: ModelProvider, index: number) => {
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...prev[provider],
        models: prev[provider].models.filter((_, idx) => idx !== index),
      },
    }));
  };

  const onModelInputKeyDown = (provider: ModelProvider, event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter') {
      return;
    }
    event.preventDefault();
    addProviderModel(provider);
  };

  const onModelDragStart = (provider: ModelProvider, index: number) => {
    setDraggingModel({ provider, index });
  };

  const onModelDrop = (provider: ModelProvider, targetIndex: number) => {
    if (!draggingModel || draggingModel.provider !== provider) {
      return;
    }
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...prev[provider],
        models: moveModel(prev[provider].models, draggingModel.index, targetIndex),
      },
    }));
    setDraggingModel(null);
  };

  const onDragOverModel = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  };

  const handleSaveProvider = (provider: ModelProvider) => {
    const form = forms[provider];
    const payload: ProviderConfigUpdate = {
      enabled: form.enabled,
      base_url: toOptionalText(form.baseUrl),
      models: normalizeModelNames(form.models),
      thinking_enabled: form.thinkingEnabled,
      thinking_level: provider === 'nvidia' ? null : toOptionalText(form.thinkingLevel) ?? 'high',
    };
    if (form.apiKey.trim()) {
      payload.api_key = form.apiKey.trim();
    } else if (form.clearApiKey) {
      payload.api_key = '';
    }

    setSavingProvider(provider);
    void updateProviderMutation
      .mutateAsync({ provider, payload })
      .then(() => {
        setForms((prev) => ({
          ...prev,
          [provider]: {
            ...prev[provider],
            apiKey: '',
            clearApiKey: false,
            modelInput: '',
          },
        }));
      })
      .finally(() => {
        setSavingProvider((prev) => (prev === provider ? null : prev));
      });
  };

  const handleApplyActiveModel = () => {
    const model = toOptionalText(activeModelDraft);
    if (!model) {
      setPageError('请选择全局生效模型');
      return;
    }
    if (!enabledProviderIds.includes(activeProviderDraft)) {
      setPageError('当前供应商未启用，请先启用后再应用全局模型');
      return;
    }
    if (!activeProviderModels.includes(model)) {
      setPageError('请从该供应商已配置模型中选择');
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
        subtitle='每个供应商可维护多个模型。保存后即可用于全局生效模型选择。'
      />

      <Alert severity='info' sx={{ mt: 0, mb: 2 }}>
        LLM 主配置（供应商、Base URL、API Key、模型列表与全局生效模型）仅在本页面生效，不再从 .env 读取。
      </Alert>

      <ErrorAlert error={mergedError} onClose={closeError} sx={{ mt: 0, mb: 2 }} />

      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} alignItems='stretch'>
        <Paper
          variant='outlined'
          sx={{
            width: { xs: '100%', lg: 280 },
            p: 1,
            borderRadius: 3,
            bgcolor: (theme) => alpha(theme.palette.background.paper, 0.9),
          }}
        >
          <Typography variant='subtitle2' color='text.secondary' sx={{ px: 1.5, py: 1 }}>
            供应商
          </Typography>
          <List disablePadding>
            {PROVIDERS.map((provider) => {
              const form = forms[provider];
              const isActiveProvider = configQuery.data?.active_provider === provider;
              const isSelected = selectedProvider === provider;
              return (
                <ListItem key={provider} disablePadding sx={{ mb: 0.5 }}>
                  <ListItemButton
                    selected={isSelected}
                    onClick={() => setSelectedProvider(provider)}
                    sx={{
                      borderRadius: 2,
                      py: 1.25,
                      '&.Mui-selected': {
                        bgcolor: (theme) =>
                          alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.12 : 0.2),
                      },
                    }}
                  >
                    <ListItemText
                      primary={PROVIDER_LABEL[provider]}
                      secondary={`${form.models.length} 个模型 · ${form.enabled ? '已启用' : '已停用'}`}
                    />
                    {isActiveProvider && <Chip label='生效中' color='success' size='small' />}
                  </ListItemButton>
                </ListItem>
              );
            })}
          </List>
        </Paper>

        <Stack spacing={2} sx={{ flex: 1 }}>
          <Paper variant='outlined' sx={{ p: 2.5, borderRadius: 3 }}>
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
                    {PROVIDERS.map((provider) => {
                      const disabled = !providerById[provider]?.enabled;
                      return (
                        <MenuItem key={provider} value={provider} disabled={disabled}>
                          {PROVIDER_LABEL[provider]}
                        </MenuItem>
                      );
                    })}
                  </Select>
                </FormControl>

                <FormControl fullWidth>
                  <InputLabel id='active-model-label'>模型</InputLabel>
                  <Select
                    labelId='active-model-label'
                    label='模型'
                    value={activeModelDraft}
                    onChange={(e) => setActiveModelDraft(String(e.target.value))}
                    disabled={activeProviderModels.length === 0}
                  >
                    {activeProviderModels.length === 0 ? (
                      <MenuItem value='' disabled>
                        暂无可选模型
                      </MenuItem>
                    ) : (
                      activeProviderModels.map((model) => (
                        <MenuItem key={model} value={model}>
                          {model}
                        </MenuItem>
                      ))
                    )}
                  </Select>
                </FormControl>

                <Button
                  variant='contained'
                  startIcon={<SettingsSuggestIcon />}
                  disabled={enabledProviderIds.length === 0 || !activeModelDraft}
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

              {enabledProviderIds.length === 0 && (
                <Alert severity='warning'>当前无启用供应商，请先启用至少一个供应商。</Alert>
              )}
            </Stack>
          </Paper>

          <Paper variant='outlined' sx={{ p: 2.5, borderRadius: 3 }}>
            <Stack spacing={2}>
              <Stack direction='row' justifyContent='space-between' alignItems='center'>
                <Typography variant='h6'>{PROVIDER_LABEL[selectedProvider]}</Typography>
                {configQuery.data?.active_provider === selectedProvider && (
                  <Chip label='当前全局生效供应商' color='success' size='small' />
                )}
              </Stack>

              <FormControlLabel
                control={
                  <Switch
                    checked={selectedProviderForm.enabled}
                    onChange={(e) => updateForm(selectedProvider, 'enabled', e.target.checked)}
                  />
                }
                label='启用供应商'
              />

              <TextField
                fullWidth
                label='Base URL'
                placeholder={selectedProvider === 'ollama' ? 'http://127.0.0.1:11434' : '可选'}
                value={selectedProviderForm.baseUrl}
                onChange={(e) => updateForm(selectedProvider, 'baseUrl', e.target.value)}
              />

              <TextField
                fullWidth
                label='API Key'
                type='password'
                placeholder={selectedProviderPersisted?.api_key_masked ?? '留空表示不修改'}
                value={selectedProviderForm.apiKey}
                onChange={(e) => updateForm(selectedProvider, 'apiKey', e.target.value)}
                helperText={
                  selectedProviderPersisted?.api_key_set
                    ? `已配置：${selectedProviderPersisted.api_key_masked ?? '******'}`
                    : '未配置'
                }
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={selectedProviderForm.clearApiKey}
                    onChange={(e) => updateForm(selectedProvider, 'clearApiKey', e.target.checked)}
                  />
                }
                label='清空已保存 API Key'
              />

              <FormControlLabel
                control={
                  <Switch
                    checked={selectedProviderForm.thinkingEnabled}
                    onChange={(e) => updateForm(selectedProvider, 'thinkingEnabled', e.target.checked)}
                  />
                }
                label='开启思考'
              />

              {selectedProvider !== 'nvidia' ? (
                <FormControl fullWidth>
                  <InputLabel id={`${selectedProvider}-thinking-level-label`}>思考强度</InputLabel>
                  <Select
                    labelId={`${selectedProvider}-thinking-level-label`}
                    label='思考强度'
                    value={selectedProviderForm.thinkingLevel || 'high'}
                    disabled={!selectedProviderForm.thinkingEnabled}
                    onChange={(e) => updateForm(selectedProvider, 'thinkingLevel', String(e.target.value))}
                  >
                    <MenuItem value='high'>high（最高）</MenuItem>
                    <MenuItem value='medium'>medium</MenuItem>
                    <MenuItem value='low'>low</MenuItem>
                  </Select>
                </FormControl>
              ) : (
                <Alert severity='info'>NVIDIA 仅支持思考开关，不支持强度分级。</Alert>
              )}

              <Box>
                <Typography variant='subtitle2' sx={{ mb: 1 }}>
                  供应商模型列表
                </Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                  <TextField
                    fullWidth
                    label='新增模型'
                    placeholder='输入模型名后回车或点击添加'
                    value={selectedProviderForm.modelInput}
                    onChange={(e) => updateForm(selectedProvider, 'modelInput', e.target.value)}
                    onKeyDown={(event) => onModelInputKeyDown(selectedProvider, event)}
                  />
                  <Button
                    variant='outlined'
                    startIcon={<AddIcon />}
                    onClick={() => addProviderModel(selectedProvider)}
                    sx={{ minWidth: 120 }}
                  >
                    添加
                  </Button>
                </Stack>

                <Stack spacing={1} sx={{ mt: 1.5 }}>
                  {selectedProviderForm.models.length === 0 ? (
                    <Alert severity='warning'>当前供应商尚未配置模型。</Alert>
                  ) : (
                    selectedProviderForm.models.map((model, index) => (
                      <Paper
                        key={`${selectedProvider}-${model}-${index}`}
                        variant='outlined'
                        draggable
                        onDragStart={() => onModelDragStart(selectedProvider, index)}
                        onDragEnd={() => setDraggingModel(null)}
                        onDragOver={onDragOverModel}
                        onDrop={() => onModelDrop(selectedProvider, index)}
                        sx={{
                          px: 1.5,
                          py: 1,
                          borderRadius: 2,
                          cursor: 'grab',
                          borderColor:
                            draggingModel?.provider === selectedProvider &&
                            draggingModel?.index === index
                              ? 'primary.main'
                              : 'divider',
                        }}
                      >
                        <Stack direction='row' spacing={1} alignItems='center'>
                          <DragIndicatorIcon fontSize='small' color='disabled' />
                          <Typography variant='body2' sx={{ flex: 1, minWidth: 0 }} noWrap>
                            {model}
                          </Typography>
                          {index === 0 && <Chip label='首选' size='small' color='primary' />}
                          <Tooltip title='删除模型'>
                            <IconButton
                              size='small'
                              onClick={() => removeProviderModel(selectedProvider, index)}
                              aria-label='删除模型'
                            >
                              <DeleteOutlineIcon fontSize='small' />
                            </IconButton>
                          </Tooltip>
                        </Stack>
                      </Paper>
                    ))
                  )}
                </Stack>
              </Box>

              <Box sx={{ pt: 1 }}>
                <Button
                  variant='contained'
                  startIcon={<SaveIcon />}
                  loading={updateProviderMutation.isPending && savingProvider === selectedProvider}
                  disabled={updateProviderMutation.isPending && savingProvider !== selectedProvider}
                  onClick={() => handleSaveProvider(selectedProvider)}
                >
                  保存配置
                </Button>
              </Box>
            </Stack>
          </Paper>
        </Stack>
      </Stack>
    </Box>
  );
}

export default ModelConfigPage;
