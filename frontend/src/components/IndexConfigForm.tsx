/**
 * 索引配置表单（主分块策略 + 通用增强策略）
 */
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  FormControl,
  FormControlLabel,
  FormLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  cloneIndexConfig,
  type ChunkingStrategy,
  type IndexConfig,
  type IndexConfigConstraints,
  type SemanticThresholdMode,
} from '../services/knowledgeBases';

interface IndexConfigFormProps {
  value: IndexConfig;
  constraints: IndexConfigConstraints;
  onChange: (next: IndexConfig) => void;
  disabled?: boolean;
  defaults?: IndexConfig;
  /**
   * UI state for main chunking strategy selection.
   *
   * - Use `null` for "not selected yet" (e.g. post-create modal).
   * - If omitted, the form falls back to `value.chunking.general_strategy` (edit mode).
   */
  mainStrategy?: ChunkingStrategy | null;
  onMainStrategyChange?: (next: ChunkingStrategy | null) => void;
}

function numberValue(value: string) {
  const parsed = Number(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function nullableNumberValue(value: string): number | null {
  if (value.trim() === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function clampWindowCount(value: number, maxWindowCount: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.max(1, Math.min(maxWindowCount, Math.trunc(value)));
}

const SEMANTIC_THRESHOLD_MODE_OPTIONS: SemanticThresholdMode[] = [
  'percentile',
  'hybrid',
  'fixed',
];

const SEMANTIC_THRESHOLD_MODE_LABELS: Record<SemanticThresholdMode, string> = {
  percentile: '百分位阈值',
  hybrid: '混合阈值',
  fixed: '固定阈值',
};

export function IndexConfigForm({
  value,
  constraints,
  onChange,
  disabled = false,
  defaults: runtimeDefaults,
  mainStrategy,
  onMainStrategyChange,
}: IndexConfigFormProps) {
  const defaults = cloneIndexConfig(runtimeDefaults ?? value);
  const selectedStrategy = mainStrategy ?? value.chunking.general_strategy;

  const updateChunking = (next: Partial<IndexConfig['chunking']>) => {
    onChange({ ...value, chunking: { ...value.chunking, ...next } });
  };
  const updateContextual = (next: Partial<IndexConfig['contextual']>) => {
    onChange({ ...value, contextual: { ...value.contextual, ...next } });
  };

  const handleMainStrategyChange = (nextStrategy: ChunkingStrategy) => {
    const prev = selectedStrategy;
    const nextConfig: IndexConfig = {
      ...value,
      chunking: { ...value.chunking, general_strategy: nextStrategy },
    };

    // 切换策略时，将离开的策略重置为默认值，避免残留隐藏的非法配置。
    if (prev && prev !== nextStrategy) {
      switch (prev) {
        case 'query_dependent_multiscale':
          nextConfig.chunking.query_dependent_multiscale =
            defaults.chunking.query_dependent_multiscale;
          break;
        case 'max_min_semantic':
          nextConfig.chunking.semantic = defaults.chunking.semantic;
          break;
        case 'parent_child':
          nextConfig.chunking.parent_child = defaults.chunking.parent_child;
          break;
        case 'markdown_heading':
          nextConfig.chunking.markdown_heading = defaults.chunking.markdown_heading;
          break;
      }
    }

    onChange(nextConfig);
    onMainStrategyChange?.(nextStrategy);
  };

  const handleContextualToggle = (enabled: boolean) => {
    if (!enabled) {
      onChange({ ...value, contextual: { ...defaults.contextual, enabled: false } });
      return;
    }
    updateContextual({ enabled: true });
  };

  const multiscaleWindows =
    value.chunking.query_dependent_multiscale.windows.length > 0
      ? value.chunking.query_dependent_multiscale.windows
      : defaults.chunking.query_dependent_multiscale.windows;

  const setMultiscaleWindows = (
    windows: IndexConfig['chunking']['query_dependent_multiscale']['windows']
  ) => {
    updateChunking({
      query_dependent_multiscale: {
        ...value.chunking.query_dependent_multiscale,
        windows,
      },
    });
  };

  const handleWindowCountChange = (nextCountRaw: string) => {
    const nextCount = clampWindowCount(
      numberValue(nextCountRaw),
      constraints.query_dependent_multiscale.window_count_max
    );
    const current = [...multiscaleWindows];
    if (nextCount <= current.length) {
      setMultiscaleWindows(current.slice(0, nextCount));
      return;
    }

    const defaultsWindows = defaults.chunking.query_dependent_multiscale.windows;
    while (current.length < nextCount) {
      const fallback =
        defaultsWindows[current.length] ?? defaultsWindows[defaultsWindows.length - 1];
      current.push({ ...fallback });
    }
    setMultiscaleWindows(current);
  };

  const updateWindowField = (
    idx: number,
    field: 'chunk_size_tokens' | 'chunk_overlap_tokens',
    rawValue: string
  ) => {
    const next = multiscaleWindows.map((window, windowIdx) =>
      windowIdx === idx ? { ...window, [field]: numberValue(rawValue) } : window
    );
    setMultiscaleWindows(next);
  };

  const semanticRangeError = value.chunking.semantic.max_tokens < value.chunking.semantic.min_tokens;
  const semanticMode = value.chunking.semantic.threshold_mode;
  const semanticNeedsPercentile = semanticMode === 'percentile' || semanticMode === 'hybrid';
  const semanticNeedsSimilarity = semanticMode === 'fixed' || semanticMode === 'hybrid';
  const semanticPercentileError =
    semanticNeedsPercentile &&
    (value.chunking.semantic.breakpoint_percentile == null ||
      value.chunking.semantic.breakpoint_percentile <
        constraints.semantic.breakpoint_percentile.min ||
      value.chunking.semantic.breakpoint_percentile >
        constraints.semantic.breakpoint_percentile.max);
  const semanticSimilarityValue = value.chunking.semantic.similarity_threshold;
  const semanticSimilarityError =
    semanticNeedsSimilarity &&
    (semanticSimilarityValue == null ||
      semanticSimilarityValue < constraints.semantic.similarity_threshold.min ||
      semanticSimilarityValue > constraints.semantic.similarity_threshold.max);
  const markdownOverlapError =
    value.chunking.markdown_heading.chunk_overlap >= value.chunking.markdown_heading.chunk_size;
  const parentOverlapError =
    value.chunking.parent_child.parent.chunk_overlap >= value.chunking.parent_child.parent.chunk_size;
  const childOverlapError =
    value.chunking.parent_child.child.chunk_overlap >= value.chunking.parent_child.child.chunk_size;
  const parentSizeError =
    value.chunking.parent_child.parent.chunk_size <= value.chunking.parent_child.child.chunk_size;
  const contextualTokensError = value.contextual.enabled && value.contextual.max_tokens < 1;

  return (
    <Stack spacing={2.5}>
      <Accordion defaultExpanded>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>分块策略</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2.5}>
            <FormControl component="fieldset">
              <FormLabel component="legend">主策略（4 选 1）</FormLabel>
              <RadioGroup
                row
                value={selectedStrategy ?? ''}
                onChange={(e) => handleMainStrategyChange(e.target.value as ChunkingStrategy)}
              >
                <FormControlLabel
                  value="query_dependent_multiscale"
                  control={<Radio />}
                  label="多尺度滑动窗口分块"
                  disabled={disabled}
                />
                <FormControlLabel
                  value="max_min_semantic"
                  control={<Radio />}
                  label="Max-Min 语义分块"
                  disabled={disabled}
                />
                <FormControlLabel
                  value="parent_child"
                  control={<Radio />}
                  label="父子分块"
                  disabled={disabled}
                />
                <FormControlLabel
                  value="markdown_heading"
                  control={<Radio />}
                  label="Markdown 标题分块"
                  disabled={disabled}
                />
              </RadioGroup>
            </FormControl>

            {selectedStrategy === 'query_dependent_multiscale' && (
              <Box>
                <Typography fontWeight={600} sx={{ mb: 1 }}>
                  多尺度滑动窗口分块参数
                </Typography>

                <TextField
                  label="window_count"
                  type="number"
                  value={multiscaleWindows.length}
                  onChange={(e) => handleWindowCountChange(e.target.value)}
                  inputProps={{ min: 1, max: constraints.query_dependent_multiscale.window_count_max }}
                  helperText={`先选择窗口数量（1~${constraints.query_dependent_multiscale.window_count_max}），再设置每个窗口参数`}
                  disabled={disabled}
                  sx={{ mb: 2, maxWidth: 280 }}
                />

                <Stack spacing={2}>
                  {multiscaleWindows.map((window, idx) => {
                    const overlapError = window.chunk_overlap_tokens >= window.chunk_size_tokens;
                    return (
                      <Stack key={`multiscale-window-${idx}`} spacing={1}>
                        <Typography variant="body2" fontWeight={600}>
                          窗口 {idx + 1}
                        </Typography>
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                          <TextField
                            label="chunk_size_tokens"
                            type="number"
                            value={window.chunk_size_tokens}
                            onChange={(e) =>
                              updateWindowField(idx, 'chunk_size_tokens', e.target.value)
                            }
                            inputProps={{
                              min: constraints.query_dependent_multiscale.window.chunk_size_tokens.min,
                              max: constraints.query_dependent_multiscale.window.chunk_size_tokens.max,
                            }}
                            helperText="token 数，窗口大小"
                            disabled={disabled}
                            fullWidth
                          />
                          <TextField
                            label="chunk_overlap_tokens"
                            type="number"
                            value={window.chunk_overlap_tokens}
                            onChange={(e) =>
                              updateWindowField(idx, 'chunk_overlap_tokens', e.target.value)
                            }
                            error={overlapError}
                            helperText={
                              overlapError
                                ? 'chunk_overlap_tokens 必须小于 chunk_size_tokens'
                                : 'token 数，窗口重叠'
                            }
                            inputProps={{
                              min: constraints.query_dependent_multiscale.window.chunk_overlap_tokens.min,
                              max: constraints.query_dependent_multiscale.window.chunk_overlap_tokens.max,
                            }}
                            disabled={disabled}
                            fullWidth
                          />
                        </Stack>
                      </Stack>
                    );
                  })}
                </Stack>
              </Box>
            )}

            {selectedStrategy === 'max_min_semantic' && (
              <Box>
                <Typography fontWeight={600} sx={{ mb: 1 }}>
                  语义分块参数
                </Typography>
                <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
                  <TextField
                    label="min_tokens"
                    type="number"
                    value={value.chunking.semantic.min_tokens}
                    onChange={(e) =>
                      updateChunking({
                        semantic: {
                          ...value.chunking.semantic,
                          min_tokens: numberValue(e.target.value),
                        },
                      })
                    }
                    inputProps={{
                      min: constraints.semantic.min_tokens.min,
                      max: constraints.semantic.min_tokens.max,
                    }}
                    disabled={disabled}
                    helperText="token 数，语义块下限"
                    fullWidth
                  />
                  <TextField
                    label="max_tokens"
                    type="number"
                    value={value.chunking.semantic.max_tokens}
                    onChange={(e) =>
                      updateChunking({
                        semantic: {
                          ...value.chunking.semantic,
                          max_tokens: numberValue(e.target.value),
                        },
                      })
                    }
                    error={semanticRangeError}
                    helperText={semanticRangeError ? 'max_tokens 必须 ≥ min_tokens' : 'token 数，语义块上限'}
                    inputProps={{
                      min: constraints.semantic.max_tokens.min,
                      max: constraints.semantic.max_tokens.max,
                    }}
                    disabled={disabled}
                    fullWidth
                  />
                </Stack>
                <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }} sx={{ mt: 2 }}>
                  <TextField
                    label="threshold_mode"
                    select
                    value={semanticMode}
                    onChange={(e) =>
                      updateChunking({
                        semantic: {
                          ...value.chunking.semantic,
                          threshold_mode: e.target.value as SemanticThresholdMode,
                        },
                      })
                    }
                    disabled={disabled}
                    helperText="语义断点阈值策略"
                    fullWidth
                  >
                    {SEMANTIC_THRESHOLD_MODE_OPTIONS.map((mode) => (
                      <MenuItem key={mode} value={mode}>
                        {SEMANTIC_THRESHOLD_MODE_LABELS[mode]}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    label="overlap_chars"
                    type="number"
                    value={value.chunking.semantic.overlap_chars}
                    onChange={(e) =>
                      updateChunking({
                        semantic: {
                          ...value.chunking.semantic,
                          overlap_chars: numberValue(e.target.value),
                        },
                      })
                    }
                    inputProps={{
                      min: constraints.semantic.overlap_chars.min,
                      max: constraints.semantic.overlap_chars.max,
                    }}
                    disabled={disabled}
                    helperText="字符数，用于语义切分的重叠"
                    fullWidth
                  />
                  <TextField
                    label="embedding_batch_size"
                    type="number"
                    value={value.chunking.semantic.embedding_batch_size}
                    onChange={(e) =>
                      updateChunking({
                        semantic: {
                          ...value.chunking.semantic,
                          embedding_batch_size: numberValue(e.target.value),
                        },
                      })
                    }
                    inputProps={{
                      min: constraints.semantic.embedding_batch_size.min,
                      max: constraints.semantic.embedding_batch_size.max,
                    }}
                    disabled={disabled}
                    helperText="句向量请求分批大小"
                    fullWidth
                  />
                </Stack>

                {(semanticNeedsPercentile || semanticNeedsSimilarity) && (
                  <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }} sx={{ mt: 2 }}>
                    {semanticNeedsPercentile && (
                      <TextField
                        label="breakpoint_percentile"
                        type="number"
                        value={value.chunking.semantic.breakpoint_percentile ?? ''}
                        onChange={(e) =>
                          updateChunking({
                            semantic: {
                              ...value.chunking.semantic,
                              breakpoint_percentile: nullableNumberValue(e.target.value),
                            },
                          })
                        }
                        error={semanticPercentileError}
                        helperText={
                          semanticPercentileError
                            ? `breakpoint_percentile 必须在 ${constraints.semantic.breakpoint_percentile.min}~${constraints.semantic.breakpoint_percentile.max}`
                            : '相邻句相似度百分位断点'
                        }
                        inputProps={{
                          min: constraints.semantic.breakpoint_percentile.min,
                          max: constraints.semantic.breakpoint_percentile.max,
                        }}
                        disabled={disabled}
                        fullWidth
                      />
                    )}

                    {semanticNeedsSimilarity && (
                      <TextField
                        label="similarity_threshold"
                        type="number"
                        value={semanticSimilarityValue ?? ''}
                        onChange={(e) =>
                          updateChunking({
                            semantic: {
                              ...value.chunking.semantic,
                              similarity_threshold: nullableNumberValue(e.target.value),
                            },
                          })
                        }
                        error={semanticSimilarityError}
                        helperText={
                          semanticSimilarityError
                            ? `similarity_threshold 必须在 ${constraints.semantic.similarity_threshold.min}~${constraints.semantic.similarity_threshold.max}`
                            : '固定相似度阈值'
                        }
                        inputProps={{
                          min: constraints.semantic.similarity_threshold.min,
                          max: constraints.semantic.similarity_threshold.max,
                          step: 0.01,
                        }}
                        disabled={disabled}
                        fullWidth
                      />
                    )}
                  </Stack>
                )}
              </Box>
            )}

            {selectedStrategy === 'parent_child' && (
              <Box>
                <Typography fontWeight={600} sx={{ mb: 1 }}>
                  父子分块参数
                </Typography>
                <Stack spacing={2}>
                  <Typography fontWeight={600}>父块</Typography>
                  <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
                    <TextField
                      label="parent.chunk_size"
                      type="number"
                      value={value.chunking.parent_child.parent.chunk_size}
                      onChange={(e) =>
                        updateChunking({
                          parent_child: {
                            ...value.chunking.parent_child,
                            parent: {
                              ...value.chunking.parent_child.parent,
                              chunk_size: numberValue(e.target.value),
                            },
                          },
                        })
                      }
                      inputProps={{
                        min: constraints.parent_child.parent.chunk_size.min,
                        max: constraints.parent_child.parent.chunk_size.max,
                      }}
                      disabled={disabled}
                      helperText="字符数，父块长度"
                      fullWidth
                    />
                    <TextField
                      label="parent.chunk_overlap"
                      type="number"
                      value={value.chunking.parent_child.parent.chunk_overlap}
                      onChange={(e) =>
                        updateChunking({
                          parent_child: {
                            ...value.chunking.parent_child,
                            parent: {
                              ...value.chunking.parent_child.parent,
                              chunk_overlap: numberValue(e.target.value),
                            },
                          },
                        })
                      }
                      error={parentOverlapError}
                      helperText={
                        parentOverlapError
                          ? 'overlap 必须小于 parent.chunk_size'
                          : '字符数，父块重叠'
                      }
                      inputProps={{
                        min: constraints.parent_child.parent.chunk_overlap.min,
                        max: constraints.parent_child.parent.chunk_overlap.max,
                      }}
                      disabled={disabled}
                      fullWidth
                    />
                  </Stack>

                  <Typography fontWeight={600}>子块</Typography>
                  <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
                    <TextField
                      label="child.chunk_size"
                      type="number"
                      value={value.chunking.parent_child.child.chunk_size}
                      onChange={(e) =>
                        updateChunking({
                          parent_child: {
                            ...value.chunking.parent_child,
                            child: {
                              ...value.chunking.parent_child.child,
                              chunk_size: numberValue(e.target.value),
                            },
                          },
                        })
                      }
                      error={parentSizeError}
                      helperText={
                        parentSizeError
                          ? 'child.chunk_size 必须小于 parent.chunk_size'
                          : '字符数，子块长度'
                      }
                      inputProps={{
                        min: constraints.parent_child.child.chunk_size.min,
                        max: constraints.parent_child.child.chunk_size.max,
                      }}
                      disabled={disabled}
                      fullWidth
                    />
                    <TextField
                      label="child.chunk_overlap"
                      type="number"
                      value={value.chunking.parent_child.child.chunk_overlap}
                      onChange={(e) =>
                        updateChunking({
                          parent_child: {
                            ...value.chunking.parent_child,
                            child: {
                              ...value.chunking.parent_child.child,
                              chunk_overlap: numberValue(e.target.value),
                            },
                          },
                        })
                      }
                      error={childOverlapError}
                      helperText={
                        childOverlapError
                          ? 'overlap 必须小于 child.chunk_size'
                          : '字符数，子块重叠'
                      }
                      inputProps={{
                        min: constraints.parent_child.child.chunk_overlap.min,
                        max: constraints.parent_child.child.chunk_overlap.max,
                      }}
                      disabled={disabled}
                      fullWidth
                    />
                  </Stack>
                </Stack>
              </Box>
            )}

            {selectedStrategy === 'markdown_heading' && (
              <Box>
                <Typography fontWeight={600} sx={{ mb: 1 }}>
                  Markdown 标题分块参数
                </Typography>
                <Stack spacing={2}>
                  <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
                    <TextField
                      label="max_heading_level"
                      type="number"
                      value={value.chunking.markdown_heading.max_heading_level}
                      onChange={(e) =>
                        updateChunking({
                          markdown_heading: {
                            ...value.chunking.markdown_heading,
                            max_heading_level: numberValue(e.target.value),
                          },
                        })
                      }
                      inputProps={{
                        min: constraints.markdown_heading.max_heading_level.min,
                        max: constraints.markdown_heading.max_heading_level.max,
                      }}
                      disabled={disabled}
                      helperText="标题层级上限"
                      fullWidth
                    />
                    <TextField
                      label="chunk_size"
                      type="number"
                      value={value.chunking.markdown_heading.chunk_size}
                      onChange={(e) =>
                        updateChunking({
                          markdown_heading: {
                            ...value.chunking.markdown_heading,
                            chunk_size: numberValue(e.target.value),
                          },
                        })
                      }
                      inputProps={{
                        min: constraints.markdown_heading.chunk_size.min,
                        max: constraints.markdown_heading.chunk_size.max,
                      }}
                      disabled={disabled}
                      helperText="字符数，章节内二次切分大小"
                      fullWidth
                    />
                    <TextField
                      label="chunk_overlap"
                      type="number"
                      value={value.chunking.markdown_heading.chunk_overlap}
                      onChange={(e) =>
                        updateChunking({
                          markdown_heading: {
                            ...value.chunking.markdown_heading,
                            chunk_overlap: numberValue(e.target.value),
                          },
                        })
                      }
                      error={markdownOverlapError}
                      helperText={
                        markdownOverlapError
                          ? 'overlap 必须小于 chunk_size'
                          : '字符数，章节内二次切分重叠'
                      }
                      inputProps={{
                        min: constraints.markdown_heading.chunk_overlap.min,
                        max: constraints.markdown_heading.chunk_overlap.max,
                      }}
                      disabled={disabled}
                      fullWidth
                    />
                  </Stack>
                </Stack>
              </Box>
            )}
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>通用增强策略</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2.5}>
            <FormControlLabel
              control={
                <Switch
                  checked={value.contextual.enabled}
                  onChange={(e) => handleContextualToggle(e.target.checked)}
                  disabled={disabled}
                />
              }
              label="启用 Contextual"
            />

            {value.contextual.enabled && (
              <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
                <TextField
                  label="max_tokens"
                  type="number"
                  value={value.contextual.max_tokens}
                  onChange={(e) =>
                    updateContextual({
                      max_tokens: numberValue(e.target.value),
                    })
                  }
                  error={contextualTokensError}
                  helperText={contextualTokensError ? '启用时必须 ≥ 1' : 'token 数，生成上下文长度'}
                  inputProps={{
                    min: constraints.contextual.max_tokens.min,
                    max: constraints.contextual.max_tokens.max,
                  }}
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label="concurrency"
                  type="number"
                  value={value.contextual.concurrency}
                  onChange={(e) =>
                    updateContextual({
                      concurrency: numberValue(e.target.value),
                    })
                  }
                  inputProps={{
                    min: constraints.contextual.concurrency.min,
                    max: constraints.contextual.concurrency.max,
                  }}
                  disabled={disabled}
                  helperText="并发数，影响吞吐与成本"
                  fullWidth
                />
              </Stack>
            )}

            <Typography variant="body2" color="text.secondary">
              检索相关参数已迁移至知识库问答初始页配置，不再在知识库创建时设置。
            </Typography>
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
