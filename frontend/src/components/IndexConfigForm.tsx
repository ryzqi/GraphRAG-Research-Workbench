/**
 * 索引配置表单（分块策略/Contextual/父子检索）
 */
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { IndexConfig, ChunkingStrategy } from '../services/knowledgeBases';

interface IndexConfigFormProps {
  value: IndexConfig;
  onChange: (next: IndexConfig) => void;
  disabled?: boolean;
}

function numberValue(value: string) {
  const parsed = Number(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function IndexConfigForm({ value, onChange, disabled = false }: IndexConfigFormProps) {
  const updateChunking = (next: Partial<IndexConfig['chunking']>) => {
    onChange({ ...value, chunking: { ...value.chunking, ...next } });
  };
  const updateContextual = (next: Partial<IndexConfig['contextual']>) => {
    onChange({ ...value, contextual: { ...value.contextual, ...next } });
  };
  const updateRetrieval = (next: Partial<IndexConfig['retrieval']>) => {
    onChange({ ...value, retrieval: { ...value.retrieval, ...next } });
  };

  const slidingOverlapError =
    value.chunking.sliding_window.chunk_overlap >= value.chunking.sliding_window.chunk_size;
  const parentOverlapError =
    value.chunking.parent_child.parent.chunk_overlap >= value.chunking.parent_child.parent.chunk_size;
  const childOverlapError =
    value.chunking.parent_child.child.chunk_overlap >= value.chunking.parent_child.child.chunk_size;
  const parentSizeError =
    value.chunking.parent_child.parent.chunk_size <= value.chunking.parent_child.child.chunk_size;
  const semanticRangeError =
    value.chunking.semantic.max_tokens < value.chunking.semantic.min_tokens;
  const contextualTokensError =
    value.contextual.enabled && value.contextual.max_tokens < 1;

  return (
    <Stack spacing={2.5}>
      <Accordion defaultExpanded>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>分块策略</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2.5}>
            <FormControl component="fieldset">
              <FormLabel component="legend">通用策略</FormLabel>
              <RadioGroup
                row
                value={value.chunking.general_strategy}
                onChange={(e) =>
                  updateChunking({ general_strategy: e.target.value as ChunkingStrategy })
                }
              >
                <FormControlLabel value="sliding_window" control={<Radio />} label="滑动窗口" disabled={disabled} />
                <FormControlLabel value="max_min_semantic" control={<Radio />} label="Max-Min 语义分块" disabled={disabled} />
                <FormControlLabel value="parent_child" control={<Radio />} label="父子分块" disabled={disabled} />
              </RadioGroup>
            </FormControl>

            <Box>
              <Typography fontWeight={600} sx={{ mb: 1 }}>
                滑动窗口参数
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField
                  label="chunk_size"
                  type="number"
                  value={value.chunking.sliding_window.chunk_size}
                  onChange={(e) =>
                    updateChunking({
                      sliding_window: {
                        ...value.chunking.sliding_window,
                        chunk_size: numberValue(e.target.value),
                      },
                    })
                  }
                  inputProps={{ min: 128, max: 20000 }}
                  disabled={disabled}
                  helperText="字符数，越大上下文更完整但召回更粗"
                  fullWidth
                />
                <TextField
                  label="chunk_overlap"
                  type="number"
                  value={value.chunking.sliding_window.chunk_overlap}
                  onChange={(e) =>
                    updateChunking({
                      sliding_window: {
                        ...value.chunking.sliding_window,
                        chunk_overlap: numberValue(e.target.value),
                      },
                    })
                  }
                  error={slidingOverlapError}
                  helperText={
                    slidingOverlapError
                      ? 'overlap 必须小于 chunk_size'
                      : '字符数，提升连续性但过大会冗余'
                  }
                  inputProps={{ min: 0, max: 2000 }}
                  disabled={disabled}
                  fullWidth
                />
              </Stack>
            </Box>

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
                  inputProps={{ min: 16, max: 1024 }}
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
                  helperText={
                    semanticRangeError ? 'max_tokens 必须 ≥ min_tokens' : 'token 数，语义块上限'
                  }
                  inputProps={{ min: 16, max: 2048 }}
                  disabled={disabled}
                  fullWidth
                />
              </Stack>
              <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }} sx={{ mt: 2 }}>
                <TextField
                  label="similarity_threshold"
                  type="number"
                  value={value.chunking.semantic.similarity_threshold}
                  onChange={(e) =>
                    updateChunking({
                      semantic: {
                        ...value.chunking.semantic,
                        similarity_threshold: numberValue(e.target.value),
                      },
                    })
                  }
                  inputProps={{ min: 0, max: 1, step: 0.01 }}
                  disabled={disabled}
                  helperText="相似度阈值，越高越容易切分"
                  fullWidth
                />
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
                  inputProps={{ min: 0, max: 2000 }}
                  disabled={disabled}
                  helperText="字符数，用于语义切分的重叠"
                  fullWidth
                />
              </Stack>
            </Box>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>Markdown 标题分块</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={value.chunking.markdown_heading.enabled}
                  onChange={(e) =>
                    updateChunking({
                      markdown_heading: {
                        ...value.chunking.markdown_heading,
                        enabled: e.target.checked,
                      },
                    })
                  }
                  disabled={disabled}
                />
              }
              label="启用标题分块"
            />
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
                inputProps={{ min: 1, max: 6 }}
                disabled={disabled}
                helperText="标题层级，1~6"
                fullWidth
              />
              <TextField
                label="max_section_chars"
                type="number"
                value={value.chunking.markdown_heading.max_section_chars}
                onChange={(e) =>
                  updateChunking({
                    markdown_heading: {
                      ...value.chunking.markdown_heading,
                      max_section_chars: numberValue(e.target.value),
                    },
                  })
                }
                inputProps={{ min: 200, max: 20000 }}
                disabled={disabled}
                helperText="单节最大字符数，超出将二次切分"
                fullWidth
              />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>父子分块参数</Typography>
        </AccordionSummary>
        <AccordionDetails>
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
                inputProps={{ min: 512, max: 20000 }}
                disabled={disabled}
                helperText="父块用于上下文，需大于子块"
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
                    ? 'overlap 必须小于 chunk_size'
                    : parentSizeError
                      ? '父块必须大于子块'
                      : '字符数，提升父块连续性'
                }
                inputProps={{ min: 0, max: 5000 }}
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
                inputProps={{ min: 128, max: 5000 }}
                disabled={disabled}
                helperText="子块用于检索，越小越精细"
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
                error={childOverlapError || parentSizeError}
                helperText={
                  childOverlapError
                    ? 'overlap 必须小于 chunk_size'
                    : parentSizeError
                      ? '父块必须大于子块'
                      : '字符数，提升子块连续性'
                }
                inputProps={{ min: 0, max: 2000 }}
                disabled={disabled}
                fullWidth
              />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>Contextual Retrieval</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={value.contextual.enabled}
                  onChange={(e) =>
                    updateContextual({
                      enabled: e.target.checked,
                    })
                  }
                  disabled={disabled}
                />
              }
              label="启用 Contextual"
            />
            <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
              <TextField
                label="timeout_seconds"
                type="number"
                value={value.contextual.timeout_seconds}
                onChange={(e) =>
                  updateContextual({
                    timeout_seconds: numberValue(e.target.value),
                  })
                }
                inputProps={{ min: 1, max: 60 }}
                disabled={disabled}
                helperText="超时秒数，过短可能失败"
                fullWidth
              />
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
                inputProps={{ min: 0, max: 512 }}
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
                inputProps={{ min: 1, max: 10 }}
                disabled={disabled}
                helperText="并发数，影响吞吐与成本"
                fullWidth
              />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography fontWeight={600}>父子检索</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={value.retrieval.parent_child.enabled}
                  onChange={(e) =>
                    updateRetrieval({
                      parent_child: {
                        ...value.retrieval.parent_child,
                        enabled: e.target.checked,
                      },
                    })
                  }
                  disabled={disabled}
                />
              }
              label="启用父子检索"
            />
            <Stack spacing={2} direction={{ xs: 'column', sm: 'row' }}>
              <TextField
                label="max_parents"
                type="number"
                value={value.retrieval.parent_child.max_parents}
                onChange={(e) =>
                  updateRetrieval({
                    parent_child: {
                      ...value.retrieval.parent_child,
                      max_parents: numberValue(e.target.value),
                    },
                  })
                }
                inputProps={{ min: 1, max: 20 }}
                disabled={disabled}
                helperText="最多保留父块数量"
                fullWidth
              />
              <TextField
                label="max_children_per_parent"
                type="number"
                value={value.retrieval.parent_child.max_children_per_parent}
                onChange={(e) =>
                  updateRetrieval({
                    parent_child: {
                      ...value.retrieval.parent_child,
                      max_children_per_parent: numberValue(e.target.value),
                    },
                  })
                }
                inputProps={{ min: 1, max: 10 }}
                disabled={disabled}
                helperText="每个父块保留的子块数"
                fullWidth
              />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
