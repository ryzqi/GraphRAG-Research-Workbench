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
import { createDefaultModelProviderFormState } from '../constants/formDefaults';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { PageHeader } from '../components/ui/PageHeader';
import {
  useModelConfig,
  useUpdateActiveModel,
  useUpdateProviderConfig,
} from '../hooks/queries/useModelConfig';
import { useRuntimeConfig } from '../hooks/queries/useRuntimeConfig';
import { getErrorMessage } from '../lib/errorHandler';
import type {
  ModelConfigRead,
  ModelProvider,
  ProviderConfigRead,
  ProviderConfigUpdate,
} from '../services/modelConfig';
import {
  indexProviderDescriptors,
  type ProviderDescriptorRead,
} from '../services/runtimeConfig';

type ProviderFormState = {
  enabled: boolean;
  baseUrl: string;
  models: string[];
  modelInput: string;
  apiKey: string;
  thinkingEnabled: boolean;
  thinkingLevel: string;
};

type PendingProviderAction =
  | {
      provider: ModelProvider;
      kind: 'save' | 'clear-api-key';
    }
  | null;

type DraggingModelState = {
  provider: ModelProvider;
  index: number;
} | null;

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

function buildForm(
  provider: ProviderConfigRead | undefined,
  descriptor: ProviderDescriptorRead | undefined
): ProviderFormState {
  const defaults = createDefaultModelProviderFormState({
    default_thinking_enabled: descriptor?.default_thinking_enabled ?? undefined,
    default_thinking_level: descriptor?.default_thinking_level ?? undefined,
  });
  if (!provider) {
    return defaults;
  }
  return {
    ...defaults,
    enabled: provider.enabled,
    baseUrl: provider.base_url ?? '',
    models: normalizeModelNames(provider.models ?? []),
    modelInput: '',
    apiKey: '',
    thinkingEnabled: descriptor?.supports_thinking_toggle === false ? false : provider.thinking_enabled,
    thinkingLevel:
      descriptor?.supports_thinking_level === false
        ? ''
        : (provider.thinking_level ?? defaults.thinkingLevel),
  };
}

function providerMap(
  config: ModelConfigRead | undefined
): Partial<Record<ModelProvider, ProviderConfigRead>> {
  const base: Partial<Record<ModelProvider, ProviderConfigRead>> = {};
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
  const runtimeConfigQuery = useRuntimeConfig();
  const updateProviderMutation = useUpdateProviderConfig();
  const updateActiveMutation = useUpdateActiveModel();
  const defaultProvider = runtimeConfigQuery.data?.default_model_provider;

  const [forms, setForms] = useState<Partial<Record<ModelProvider, ProviderFormState>>>({});
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(defaultProvider ?? null);
  const [activeProviderDraft, setActiveProviderDraft] =
    useState<ModelProvider | null>(defaultProvider ?? null);
  const [activeModelDraft, setActiveModelDraft] = useState('');
  const [pageError, setPageError] = useState<string | null>(null);
  const [pendingProviderAction, setPendingProviderAction] = useState<PendingProviderAction>(null);
  const [draggingModel, setDraggingModel] = useState<DraggingModelState>(null);

  const providerDescriptors = useMemo(
    () => runtimeConfigQuery.data?.providers ?? [],
    [runtimeConfigQuery.data]
  );
  const providerDescriptorById = useMemo(
    () => indexProviderDescriptors(providerDescriptors),
    [providerDescriptors]
  );
  const providerIds = useMemo(() => {
    if (providerDescriptors.length > 0) {
      return providerDescriptors.map((item) => item.provider);
    }
    return (configQuery.data?.providers ?? []).map((item) => item.provider);
  }, [providerDescriptors, configQuery.data]);
  const providerById = useMemo(() => providerMap(configQuery.data), [configQuery.data]);
  const buildDefaultForm = (provider: ModelProvider): ProviderFormState =>
    createDefaultModelProviderFormState({
      default_thinking_enabled: providerDescriptorById[provider]?.default_thinking_enabled ?? undefined,
      default_thinking_level: providerDescriptorById[provider]?.default_thinking_level ?? undefined,
    });
  const resolvedSelectedProvider = selectedProvider ?? defaultProvider ?? providerIds[0] ?? null;
  const getProviderForm = (provider: ModelProvider): ProviderFormState =>
    forms[provider] ?? buildDefaultForm(provider);
  const selectedProviderForm = resolvedSelectedProvider
    ? getProviderForm(resolvedSelectedProvider)
    : null;
  const selectedProviderPersisted = resolvedSelectedProvider ? providerById[resolvedSelectedProvider] : undefined;

  useEffect(() => {
    const config = configQuery.data;
    if (!config) {
      return;
    }
    const providerLookup = providerMap(config);
    const nextForms: Partial<Record<ModelProvider, ProviderFormState>> = {};
    const orderedProviders =
      providerIds.length > 0 ? providerIds : config.providers.map((item) => item.provider);
    for (const provider of orderedProviders) {
      nextForms[provider] = buildForm(
        providerLookup[provider],
        providerDescriptorById[provider]
      );
    }
    setForms(nextForms);
    setSelectedProvider(config.active_provider);
    setActiveProviderDraft(config.active_provider);
    setActiveModelDraft(config.active_model ?? '');
  }, [configQuery.data, providerIds, providerDescriptorById]);

  useEffect(() => {
    if (defaultProvider && selectedProvider === null) {
      setSelectedProvider(defaultProvider);
    }
    if (defaultProvider && activeProviderDraft === null) {
      setActiveProviderDraft(defaultProvider);
    }
  }, [activeProviderDraft, defaultProvider, selectedProvider]);

  const mergedError =
    pageError ??
    (runtimeConfigQuery.error ? getErrorMessage(runtimeConfigQuery.error) : null) ??
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
    if (runtimeConfigQuery.error) {
      void runtimeConfigQuery.refetch();
      return;
    }
    if (configQuery.error) {
      void configQuery.refetch();
    }
  };

  const enabledProviderIds = useMemo(
    () => providerIds.filter((provider) => providerById[provider]?.enabled),
    [providerIds, providerById]
  );

  const effectiveActiveProviderDraft =
    !activeProviderDraft ||
    enabledProviderIds.length === 0 ||
    enabledProviderIds.includes(activeProviderDraft)
      ? activeProviderDraft
      : enabledProviderIds[0];

  const activeProviderModels = useMemo(() => {
    if (!effectiveActiveProviderDraft) {
      return [];
    }
    return providerById[effectiveActiveProviderDraft]?.models ?? [];
  }, [effectiveActiveProviderDraft, providerById]);

  const effectiveActiveModelDraft =
    activeProviderModels.length === 0 || activeProviderModels.includes(activeModelDraft)
      ? activeModelDraft
      : activeProviderModels[0];
  const isSavingSelectedProvider =
    updateProviderMutation.isPending &&
    pendingProviderAction?.provider === resolvedSelectedProvider &&
    pendingProviderAction.kind === 'save';
  const isClearingApiKeyForSelectedProvider =
    updateProviderMutation.isPending &&
    pendingProviderAction?.provider === resolvedSelectedProvider &&
    pendingProviderAction.kind === 'clear-api-key';
  const selectedProviderSupportsThinkingToggle = resolvedSelectedProvider
    ? (providerDescriptorById[resolvedSelectedProvider]?.supports_thinking_toggle ?? true)
    : true;
  const selectedProviderSupportsThinkingLevel = resolvedSelectedProvider
    ? (providerDescriptorById[resolvedSelectedProvider]?.supports_thinking_level ?? true)
    : true;
  const getProviderLabel = (provider: ModelProvider): string =>
    providerDescriptorById[provider]?.label ?? provider;
  const getProviderBaseUrlPlaceholder = (provider: ModelProvider): string =>
    providerDescriptorById[provider]?.base_url_placeholder ?? '';
  const getProviderBaseUrlHelperText = (provider: ModelProvider): string | undefined =>
    providerDescriptorById[provider]?.base_url_helper_text ?? undefined;

  const updateForm = <K extends keyof ProviderFormState>(
    provider: ModelProvider,
    key: K,
    value: ProviderFormState[K]
  ) => {
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...(prev[provider] ?? buildDefaultForm(provider)),
        [key]: value,
      },
    }));
  };

  const addProviderModel = (provider: ModelProvider) => {
    const form = getProviderForm(provider);
    const candidate = form.modelInput.trim();
    if (!candidate) {
      return;
    }
    const models = normalizeModelNames([...form.models, candidate]);
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...(prev[provider] ?? buildDefaultForm(provider)),
        models,
        modelInput: '',
      },
    }));
  };

  const removeProviderModel = (provider: ModelProvider, index: number) => {
    setForms((prev) => ({
      ...prev,
      [provider]: {
        ...(prev[provider] ?? buildDefaultForm(provider)),
        models: (prev[provider] ?? buildDefaultForm(provider)).models.filter((_, idx) => idx !== index),
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
        ...(prev[provider] ?? buildDefaultForm(provider)),
        models: moveModel(
          (prev[provider] ?? buildDefaultForm(provider)).models,
          draggingModel.index,
          targetIndex
        ),
      },
    }));
    setDraggingModel(null);
  };

  const onDragOverModel = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  };

  const handleSaveProvider = (provider: ModelProvider) => {
    const descriptor = providerDescriptorById[provider];
    const form = getProviderForm(provider);
    const payload: ProviderConfigUpdate = {
      enabled: form.enabled,
      base_url: toOptionalText(form.baseUrl),
      models: normalizeModelNames(form.models),
      thinking_enabled: descriptor?.supports_thinking_toggle === false ? false : form.thinkingEnabled,
      thinking_level:
        descriptor?.supports_thinking_level === false
          ? null
          : toOptionalText(form.thinkingLevel) ?? descriptor?.default_thinking_level ?? 'high',
    };
    if (form.apiKey.trim()) {
      payload.api_key = form.apiKey.trim();
    }

    setPendingProviderAction({ provider, kind: 'save' });
    void updateProviderMutation
      .mutateAsync({ provider, payload })
      .then(() => {
        setForms((prev) => ({
          ...prev,
          [provider]: {
            ...prev[provider],
            apiKey: '',
            modelInput: '',
          },
        }));
      })
      .finally(() => {
        setPendingProviderAction((prev) =>
          prev?.provider === provider && prev.kind === 'save' ? null : prev
        );
      });
  };

  const handleClearProviderApiKey = (provider: ModelProvider) => {
    setPendingProviderAction({ provider, kind: 'clear-api-key' });
    void updateProviderMutation
      .mutateAsync({
        provider,
        payload: { api_key: '' },
      })
      .then(() => {
        setForms((prev) => ({
          ...prev,
          [provider]: {
            ...prev[provider],
            apiKey: '',
          },
        }));
      })
      .finally(() => {
        setPendingProviderAction((prev) =>
          prev?.provider === provider && prev.kind === 'clear-api-key' ? null : prev
        );
      });
  };

  const handleApplyActiveModel = () => {
    if (!effectiveActiveProviderDraft) {
      setPageError('运行时默认供应商尚未加载完成');
      return;
    }
    const model = toOptionalText(effectiveActiveModelDraft);
    if (!model) {
      setPageError('请选择全局生效模型');
      return;
    }
    if (!enabledProviderIds.includes(effectiveActiveProviderDraft)) {
      setPageError('当前供应商未启用，请先启用后再应用全局模型');
      return;
    }
    if (!activeProviderModels.includes(model)) {
      setPageError('请从该供应商已配置模型中选择');
      return;
    }
    updateActiveMutation.mutate({
      provider: effectiveActiveProviderDraft,
      model,
    });
  };

  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 3 }}>
      <PageHeader
        title='模型配置'
        subtitle='每个供应商可维护多个模型。保存后即可用于全局生效模型选择。'
      />

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
            {providerIds.map((provider) => {
              const form = forms[provider];
              const isActiveProvider = configQuery.data?.active_provider === provider;
              const isSelected = resolvedSelectedProvider === provider;
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
                      primary={getProviderLabel(provider)}
                      secondary={`${(form ?? buildDefaultForm(provider)).models.length} 个模型 · ${
                        (form ?? buildDefaultForm(provider)).enabled ? '已启用' : '已停用'
                      }`}
                    />
                    {isActiveProvider && <Chip label='生效中' color='success' size='small' />}
                  </ListItemButton>
                </ListItem>
              );
            })}
          </List>
        </Paper>

        <Stack spacing={2} sx={{ flex: 1 }}>
          {!resolvedSelectedProvider && (
            <Alert severity='info'>正在加载运行时默认模型供应商…</Alert>
          )}
          <Paper variant='outlined' sx={{ p: 2.5, borderRadius: 3 }}>
            <Stack spacing={2}>
              <Typography variant='h6'>全局生效模型</Typography>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                <FormControl fullWidth>
                  <InputLabel id='active-provider-label'>供应商</InputLabel>
                  <Select
                    labelId='active-provider-label'
                    label='供应商'
                    value={effectiveActiveProviderDraft ?? ''}
                    onChange={(e) => setActiveProviderDraft(e.target.value as ModelProvider)}
                  >
                    {providerIds.map((provider) => {
                      const disabled = !providerById[provider]?.enabled;
                      return (
                        <MenuItem key={provider} value={provider} disabled={disabled}>
                          {getProviderLabel(provider)}
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
                    value={effectiveActiveModelDraft}
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
                  disabled={enabledProviderIds.length === 0 || !effectiveActiveModelDraft}
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
                    label={`${getProviderLabel(configQuery.data.active_provider)} / ${configQuery.data.active_model ?? '-'}`}
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
                <Typography variant='h6'>
                  {resolvedSelectedProvider ? getProviderLabel(resolvedSelectedProvider) : '供应商'}
                </Typography>
                {resolvedSelectedProvider && configQuery.data?.active_provider === resolvedSelectedProvider && (
                  <Chip label='当前全局生效供应商' color='success' size='small' />
                )}
              </Stack>

              <FormControlLabel
                control={
                  <Switch
                    checked={selectedProviderForm?.enabled ?? false}
                    onChange={(e) =>
                      resolvedSelectedProvider &&
                      updateForm(resolvedSelectedProvider, 'enabled', e.target.checked)
                    }
                  />
                }
                label='启用供应商'
                disabled={!resolvedSelectedProvider}
              />

              <TextField
                fullWidth
                label='Base URL'
                placeholder={resolvedSelectedProvider ? getProviderBaseUrlPlaceholder(resolvedSelectedProvider) : ''}
                value={selectedProviderForm?.baseUrl ?? ''}
                onChange={(e) =>
                  resolvedSelectedProvider && updateForm(resolvedSelectedProvider, 'baseUrl', e.target.value)
                }
                helperText={resolvedSelectedProvider ? getProviderBaseUrlHelperText(resolvedSelectedProvider) : undefined}
                disabled={!resolvedSelectedProvider}
              />

              <TextField
                fullWidth
                label='API Key'
                type='password'
                placeholder={selectedProviderPersisted?.api_key_masked ?? '留空表示不修改'}
                value={selectedProviderForm?.apiKey ?? ''}
                onChange={(e) =>
                  resolvedSelectedProvider && updateForm(resolvedSelectedProvider, 'apiKey', e.target.value)
                }
                helperText={
                  resolvedSelectedProvider && providerDescriptorById[resolvedSelectedProvider]?.api_key_optional
                    ? selectedProviderPersisted?.api_key_set
                      ? `已配置：${selectedProviderPersisted.api_key_masked ?? '******'}`
                      : '本地无鉴权可留空；如通过反向代理增加鉴权，可填写。'
                    : selectedProviderPersisted?.api_key_set
                    ? `已配置：${selectedProviderPersisted.api_key_masked ?? '******'}`
                    : '未配置'
                }
                disabled={!resolvedSelectedProvider}
              />
              {selectedProviderPersisted?.api_key_set ? (
                <Button
                  variant='outlined'
                  color='error'
                  startIcon={<DeleteOutlineIcon />}
                  loading={isClearingApiKeyForSelectedProvider}
                  disabled={updateProviderMutation.isPending && !isClearingApiKeyForSelectedProvider}
                  onClick={() => resolvedSelectedProvider && handleClearProviderApiKey(resolvedSelectedProvider)}
                  sx={{ alignSelf: 'flex-start' }}
                >
                  清空已保存 API Key
                </Button>
              ) : null}

              {selectedProviderSupportsThinkingToggle ? (
                <>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={selectedProviderForm?.thinkingEnabled ?? false}
                        onChange={(e) =>
                          resolvedSelectedProvider &&
                          updateForm(resolvedSelectedProvider, 'thinkingEnabled', e.target.checked)
                        }
                      />
                    }
                    label='开启思考'
                    disabled={!resolvedSelectedProvider}
                  />

                  {selectedProviderSupportsThinkingLevel ? (
                    <FormControl fullWidth>
                      <InputLabel id={`${resolvedSelectedProvider ?? 'provider'}-thinking-level-label`}>
                        思考强度
                      </InputLabel>
                      <Select
                        labelId={`${resolvedSelectedProvider ?? 'provider'}-thinking-level-label`}
                        label='思考强度'
                        value={selectedProviderForm?.thinkingLevel || 'high'}
                        disabled={!resolvedSelectedProvider || !selectedProviderForm?.thinkingEnabled}
                        onChange={(e) =>
                          resolvedSelectedProvider &&
                          updateForm(resolvedSelectedProvider, 'thinkingLevel', String(e.target.value))
                        }
                      >
                        <MenuItem value='high'>high（最高）</MenuItem>
                        <MenuItem value='medium'>medium</MenuItem>
                        <MenuItem value='low'>low</MenuItem>
                      </Select>
                    </FormControl>
                  ) : (
                    <Alert severity='info'>NVIDIA 仅支持思考开关，不支持强度分级。</Alert>
                  )}
                </>
              ) : (
                <Alert severity='info'>
                  llama.cpp 的 thinking 行为由 `llama-server` 启动参数控制，页面不提供单独配置。
                </Alert>
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
                    value={selectedProviderForm?.modelInput ?? ''}
                    onChange={(e) =>
                      resolvedSelectedProvider &&
                      updateForm(resolvedSelectedProvider, 'modelInput', e.target.value)
                    }
                    onKeyDown={(event) =>
                      resolvedSelectedProvider && onModelInputKeyDown(resolvedSelectedProvider, event)
                    }
                    disabled={!resolvedSelectedProvider}
                  />
                  <Button
                    variant='outlined'
                    startIcon={<AddIcon />}
                    onClick={() => resolvedSelectedProvider && addProviderModel(resolvedSelectedProvider)}
                    disabled={!resolvedSelectedProvider}
                    sx={{ minWidth: 120 }}
                  >
                    添加
                  </Button>
                </Stack>

                <Stack spacing={1} sx={{ mt: 1.5 }}>
                  {!selectedProviderForm || selectedProviderForm.models.length === 0 ? (
                    <Alert severity='warning'>当前供应商尚未配置模型。</Alert>
                  ) : (
                    selectedProviderForm.models.map((model, index) => (
                      <Paper
                        key={`${resolvedSelectedProvider}-${model}-${index}`}
                        variant='outlined'
                        draggable
                        onDragStart={() => resolvedSelectedProvider && onModelDragStart(resolvedSelectedProvider, index)}
                        onDragEnd={() => setDraggingModel(null)}
                        onDragOver={onDragOverModel}
                        onDrop={() => resolvedSelectedProvider && onModelDrop(resolvedSelectedProvider, index)}
                        sx={{
                          px: 1.5,
                          py: 1,
                          borderRadius: 2,
                          cursor: 'grab',
                          borderColor:
                            draggingModel?.provider === resolvedSelectedProvider &&
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
                              onClick={() =>
                                resolvedSelectedProvider && removeProviderModel(resolvedSelectedProvider, index)
                              }
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
                  loading={isSavingSelectedProvider}
                  disabled={!resolvedSelectedProvider || (updateProviderMutation.isPending && !isSavingSelectedProvider)}
                  onClick={() => resolvedSelectedProvider && handleSaveProvider(resolvedSelectedProvider)}
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
