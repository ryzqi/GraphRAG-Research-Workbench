import {
  Alert,
  Box,
  Grid,
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

  const errors = validateKbChatConfig(value);
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
                  label='Hybrid RRF k'
                  type='number'
                  value={value.retrieval_hybrid_rrf_k}
                  onChange={(event) => handleIntField('retrieval_hybrid_rrf_k', event.target.value)}
                  inputProps={{ min: 1, max: 200 }}
                  helperText='控制 Milvus 原生 hybrid_search 的 RRF 平滑度；调大更平滑，调小更偏向前排结果。'
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
