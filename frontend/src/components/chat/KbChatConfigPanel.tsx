import {
  Alert,
  Box,
  Grid,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest';
import PrecisionManufacturingIcon from '@mui/icons-material/PrecisionManufacturing';
import { alpha } from '@mui/material/styles';
import type { Theme } from '@mui/material/styles';

import type { KbChatConfig } from '../../services/chats';
import { validateKbChatConfig } from '../../services/kbChatConfig';

interface KbChatConfigPanelProps {
  value: KbChatConfig;
  onChange: (next: KbChatConfig) => void;
  disabled?: boolean;
  parentChildLimitsEnabled?: boolean;
}

const SECTION_SX = {
  p: 1.5,
  borderRadius: 2.5,
  border: 1,
  borderColor: (theme: Theme) => alpha(theme.palette.primary.main, 0.18),
  bgcolor: (theme: Theme) =>
    theme.palette.mode === 'light'
      ? alpha(theme.palette.common.white, 0.7)
      : alpha(theme.palette.background.default, 0.32),
};

function toInt(value: string): number | null {
  if (value.trim() === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
}

function toFloat(value: string): number | null {
  if (value.trim() === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function KbChatConfigPanel({
  value,
  onChange,
  disabled = false,
  parentChildLimitsEnabled = true,
}: KbChatConfigPanelProps) {
  const handleIntField = (key: keyof KbChatConfig, raw: string) => {
    const parsed = toInt(raw);
    if (parsed === null) {
      return;
    }
    onChange({ ...value, [key]: parsed });
  };

  const handleFloatField = (key: keyof KbChatConfig, raw: string) => {
    const parsed = toFloat(raw);
    if (parsed === null) {
      return;
    }
    onChange({ ...value, [key]: parsed });
  };

  const errors = validateKbChatConfig(value);
  const isWeightedRanker = value.retrieval_hybrid_ranker === 'weighted';
  const hybridRankerHelperText = isWeightedRanker
    ? '当前 Weighted：按 Dense/BM25 权重融合，便于精细控制召回偏好。'
    : '当前 RRF：按排名融合，通常更稳健且无需调 Dense/BM25 权重。';
  const hybridRrfKHelperText = isWeightedRanker
    ? '当前 Weighted 模式下不生效；切换到 RRF 后用于控制融合平滑度。'
    : '控制 RRF 对排名差异的敏感度；调大更平滑，调小更偏向前排结果。';
  const denseWeightHelperText = isWeightedRanker
    ? 'Weighted 生效：调大后更偏向语义（Dense）召回结果。'
    : '当前 RRF 模式：该参数暂不生效，切换 Weighted 后可调语义召回占比。';
  const sparseWeightHelperText = isWeightedRanker
    ? 'Weighted 生效：调大后更偏向关键词（BM25）召回结果。'
    : '当前 RRF 模式：该参数暂不生效，切换 Weighted 后可调关键词召回占比。';
  const parentChildLimitStateText = parentChildLimitsEnabled ? '父子分块生效' : '仅父子分块生效';
  const parentChildLimitDisabled = disabled || !parentChildLimitsEnabled;
  const parentMaxParentsHelperText = `${parentChildLimitStateText}；控制可保留父块数，调大可提升覆盖但会增加噪声。`;
  const parentMaxChildrenHelperText = `${parentChildLimitStateText}；控制每个父块保留子块数，调大可补充细节但更占上下文。`;

  return (
    <Paper
      variant='outlined'
      sx={{
        p: { xs: 2, md: 2.5 },
        borderRadius: 3.5,
        borderColor: (theme) => alpha(theme.palette.primary.main, 0.25),
        bgcolor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.common.white, 0.82)
            : alpha(theme.palette.background.paper, 0.56),
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
      }}
    >
      <Stack spacing={2}>
        <Stack direction='row' spacing={1} alignItems='center' flexWrap='wrap' useFlexGap>
          <SettingsSuggestIcon color='primary' fontSize='small' />
          <Typography variant='subtitle1' fontWeight={700}>
            问答检索参数面板
          </Typography>
        </Stack>

        {errors.length > 0 && (
          <Alert severity='warning' variant='outlined'>
            {errors.join('；')}
          </Alert>
        )}

        <Grid container spacing={1.5}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Box sx={SECTION_SX}>
              <Stack spacing={1.2}>
                <Stack direction='row' spacing={1} alignItems='center'>
                  <PrecisionManufacturingIcon fontSize='small' color='primary' />
                  <Typography variant='subtitle2' fontWeight={700}>
                    检索与扩展参数
                  </Typography>
                </Stack>
                <TextField
                  label='检索 Top-K'
                  type='number'
                  value={value.retrieval_top_k}
                  onChange={(event) => handleIntField('retrieval_top_k', event.target.value)}
                  inputProps={{ min: 1, max: 20 }}
                  helperText='控制初次召回数量；调大可提高覆盖率，但会增加噪声与耗时。'
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label='重排序 Top-K'
                  type='number'
                  value={value.retrieval_rerank_top_k}
                  onChange={(event) => handleIntField('retrieval_rerank_top_k', event.target.value)}
                  inputProps={{ min: value.retrieval_top_k, max: 50 }}
                  helperText={`控制进入重排序的候选量；调大可提升命中率但更耗时（范围 ${value.retrieval_top_k}~50）。`}
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label='实体扩展候选上限'
                  type='number'
                  value={value.entity_expand_max_candidates}
                  onChange={(event) =>
                    handleIntField('entity_expand_max_candidates', event.target.value)
                  }
                  inputProps={{ min: 1, max: 12 }}
                  helperText='实体扩展节点按需触发时使用该候选池大小，召回优先建议 6~10。'
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label='实体扩展输出上限'
                  type='number'
                  value={value.entity_expand_max_variants}
                  onChange={(event) =>
                    handleIntField('entity_expand_max_variants', event.target.value)
                  }
                  inputProps={{ min: 1, max: 12 }}
                  helperText='实体扩展节点按需触发时保留的最终查询数，需小于等于候选上限。'
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label='实体扩展最小置信度'
                  type='number'
                  value={value.entity_expand_min_confidence}
                  onChange={(event) =>
                    handleFloatField('entity_expand_min_confidence', event.target.value)
                  }
                  inputProps={{ min: 0, max: 1, step: 0.05 }}
                  helperText='实体扩展节点按需触发时，低于该置信度的候选会被剪枝。'
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label='实体扩展超时（秒）'
                  type='number'
                  value={value.entity_expand_timeout_seconds}
                  onChange={(event) =>
                    handleFloatField('entity_expand_timeout_seconds', event.target.value)
                  }
                  inputProps={{ min: 0, max: 5, step: 0.1 }}
                  helperText='实体扩展节点按需触发时的模型超时，超时后自动降级。'
                  disabled={disabled}
                  fullWidth
                />
                <TextField
                  label='Hybrid Ranker'
                  select
                  value={value.retrieval_hybrid_ranker}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      retrieval_hybrid_ranker: event.target.value as KbChatConfig['retrieval_hybrid_ranker'],
                    })
                  }
                  helperText={hybridRankerHelperText}
                  disabled={disabled}
                  fullWidth
                >
                  <MenuItem value='rrf'>RRF</MenuItem>
                  <MenuItem value='weighted'>Weighted</MenuItem>
                </TextField>
                <TextField
                  label='Hybrid RRF k'
                  type='number'
                  value={value.retrieval_hybrid_rrf_k}
                  onChange={(event) => handleIntField('retrieval_hybrid_rrf_k', event.target.value)}
                  inputProps={{ min: 1, max: 200 }}
                  helperText={hybridRrfKHelperText}
                  disabled={disabled}
                  fullWidth
                />
              </Stack>
            </Box>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }}>
            <Box sx={SECTION_SX}>
              <Stack spacing={1.2}>
                <Typography variant='subtitle2' fontWeight={700}>
                  融合与策略限制参数
                </Typography>
                <Grid container spacing={1.2}>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='Dense 权重'
                      type='number'
                      value={value.retrieval_hybrid_dense_weight}
                      onChange={(event) => handleFloatField('retrieval_hybrid_dense_weight', event.target.value)}
                      inputProps={{ min: 0, max: 1, step: 0.05 }}
                      helperText={denseWeightHelperText}
                      disabled={disabled || value.retrieval_hybrid_ranker !== 'weighted'}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='BM25 权重'
                      type='number'
                      value={value.retrieval_hybrid_sparse_weight}
                      onChange={(event) => handleFloatField('retrieval_hybrid_sparse_weight', event.target.value)}
                      inputProps={{ min: 0, max: 1, step: 0.05 }}
                      helperText={sparseWeightHelperText}
                      disabled={disabled || value.retrieval_hybrid_ranker !== 'weighted'}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='父块保留上限'
                      type='number'
                      value={value.retrieval_parent_max_parents}
                      onChange={(event) => handleIntField('retrieval_parent_max_parents', event.target.value)}
                      inputProps={{ min: 1, max: 20 }}
                      helperText={parentMaxParentsHelperText}
                      disabled={parentChildLimitDisabled}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='每父块子块上限'
                      type='number'
                      value={value.retrieval_parent_max_children_per_parent}
                      onChange={(event) =>
                        handleIntField('retrieval_parent_max_children_per_parent', event.target.value)
                      }
                      inputProps={{ min: 1, max: 10 }}
                      helperText={parentMaxChildrenHelperText}
                      disabled={parentChildLimitDisabled}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='多尺度窗口 Top-K'
                      type='number'
                      value={value.retrieval_multiscale_per_window_top_k}
                      onChange={(event) =>
                        handleIntField('retrieval_multiscale_per_window_top_k', event.target.value)
                      }
                      inputProps={{ min: 1, max: 200 }}
                      helperText='控制每个尺度窗口的候选量；调大可提高覆盖，但会增加计算开销。'
                      disabled={disabled}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='多尺度 RRF k'
                      type='number'
                      value={value.retrieval_multiscale_rrf_k}
                      onChange={(event) => handleIntField('retrieval_multiscale_rrf_k', event.target.value)}
                      inputProps={{ min: 1, max: 200 }}
                      helperText='控制多尺度融合平滑度；调大更均衡，调小更偏向高排结果。'
                      disabled={disabled}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='文档保留上限'
                      type='number'
                      value={value.retrieval_multiscale_max_documents}
                      onChange={(event) =>
                        handleIntField('retrieval_multiscale_max_documents', event.target.value)
                      }
                      inputProps={{ min: 1, max: 100 }}
                      helperText='限制进入多尺度阶段的文档数；调大更全面，但噪声和耗时会增加。'
                      disabled={disabled}
                      fullWidth
                    />
                  </Grid>
                  <Grid size={{ xs: 12, md: 6 }}>
                    <TextField
                      label='每文档 Chunk 上限'
                      type='number'
                      value={value.retrieval_multiscale_max_chunks_per_document}
                      onChange={(event) =>
                        handleIntField('retrieval_multiscale_max_chunks_per_document', event.target.value)
                      }
                      inputProps={{ min: 1, max: 20 }}
                      helperText='限制单文档保留的 Chunk 数；调大可补充细节，但会挤占其他文档配额。'
                      disabled={disabled}
                      fullWidth
                    />
                  </Grid>
                </Grid>
              </Stack>
            </Box>
          </Grid>
        </Grid>

      </Stack>
    </Paper>
  );
}
