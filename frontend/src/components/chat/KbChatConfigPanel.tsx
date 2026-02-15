import type { ReactNode } from 'react';
import { Box, Chip, FormControlLabel, Grid, Paper, Stack, Switch, Typography } from '@mui/material';
import TuneIcon from '@mui/icons-material/Tune';
import RouteIcon from '@mui/icons-material/Route';
import FindInPageIcon from '@mui/icons-material/FindInPage';
import { alpha } from '@mui/material/styles';

import type { KbChatConfig } from '../../services/chats';

interface KbChatConfigPanelProps {
  value: KbChatConfig;
  onChange: (next: KbChatConfig) => void;
  disabled?: boolean;
}

interface ToggleDef {
  key: keyof KbChatConfig;
  label: string;
  description: string;
}

interface ToggleGroupDef {
  id: string;
  title: string;
  icon: ReactNode;
  toggles: ToggleDef[];
}

const GROUPS: ToggleGroupDef[] = [
  {
    id: 'preprocess',
    title: '预处理',
    icon: <RouteIcon fontSize="small" />,
    toggles: [
      {
        key: 'query_rewrite_enabled',
        label: '查询改写',
        description: '在检索前改写问题，提高召回稳定性。',
      },
      {
        key: 'ambiguity_check_enabled',
        label: '歧义检测',
        description: '先判断问题是否缺少关键信息，必要时引导澄清。',
      },
      {
        key: 'decomposition_enabled',
        label: '问题分解',
        description: '把复杂问题拆成子问题；与多路查询互斥。',
      },
      {
        key: 'multi_query_enabled',
        label: '多路查询',
        description: '为问题生成多个变体并融合检索结果；与问题分解互斥。',
      },
      {
        key: 'hyde_enabled',
        label: 'HyDE',
        description: '生成假设文档参与检索，提升语义命中概率。',
      },
    ],
  },
  {
    id: 'retrieval',
    title: '检索',
    icon: <FindInPageIcon fontSize="small" />,
    toggles: [
      {
        key: 'hybrid_retrieval_enabled',
        label: '混合检索',
        description: '同时使用 Dense + BM25 召回，再做融合排序。',
      },
      {
        key: 'rerank_enabled',
        label: '重排序',
        description: '对候选证据做语义重排，提升 Top-N 质量。',
      },
    ],
  },
];

export function KbChatConfigPanel({ value, onChange, disabled = false }: KbChatConfigPanelProps) {
  const handleToggle = (key: keyof KbChatConfig, checked: boolean) => {
    let next: KbChatConfig = { ...value, [key]: checked };
    if (key === 'decomposition_enabled' && checked) {
      next = { ...next, multi_query_enabled: false };
    }
    if (key === 'multi_query_enabled' && checked) {
      next = { ...next, decomposition_enabled: false };
    }
    onChange(next);
  };

  const enabledCount = Object.values(value).filter(Boolean).length;
  const totalCount = Object.keys(value).length;

  return (
    <Paper
      variant="outlined"
      sx={{
        p: { xs: 2, md: 2.5 },
        borderRadius: 3.5,
        borderColor: (theme) => alpha(theme.palette.primary.main, 0.22),
        bgcolor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.common.white, 0.78)
            : alpha(theme.palette.background.paper, 0.56),
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
      }}
    >
      <Stack spacing={2}>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
          <TuneIcon color="primary" fontSize="small" />
          <Typography variant="subtitle1" fontWeight={700}>
            回答链路配置
          </Typography>
          <Chip label={`已开启 ${enabledCount}/${totalCount}`} size="small" color="primary" variant="outlined" />
        </Stack>
        <Typography variant="body2" color="text.secondary">
          配置会在本会话内固定生效，便于复现回答结果与排查差异。
        </Typography>

        <Grid container spacing={1.5}>
          {GROUPS.map((group) => (
            <Grid key={group.id} size={{ xs: 12, md: 6 }}>
              <Paper
                variant="outlined"
                sx={{
                  p: 1.5,
                  borderRadius: 2.5,
                  height: '100%',
                  borderColor: (theme) => alpha(theme.palette.primary.main, 0.16),
                  bgcolor: (theme) =>
                    theme.palette.mode === 'light'
                      ? alpha(theme.palette.background.paper, 0.82)
                      : alpha(theme.palette.background.default, 0.34),
                }}
              >
                <Stack spacing={1}>
                  <Stack direction="row" alignItems="center" spacing={0.75}>
                    {group.icon}
                    <Typography variant="subtitle2" fontWeight={700}>
                      {group.title}
                    </Typography>
                  </Stack>
                  {group.toggles.map((item) => (
                    <Box
                      key={item.key}
                      sx={{
                        px: 1,
                        py: 0.75,
                        borderRadius: 1.5,
                        transition: 'background-color 180ms ease',
                        '&:hover': {
                          bgcolor: (theme) => alpha(theme.palette.primary.main, 0.06),
                        },
                      }}
                    >
                      <FormControlLabel
                        sx={{ m: 0, width: '100%', alignItems: 'flex-start' }}
                        control={
                          <Switch
                            checked={value[item.key]}
                            disabled={disabled}
                            onChange={(_, checked) => handleToggle(item.key, checked)}
                            inputProps={{ 'aria-label': item.label }}
                          />
                        }
                        label={
                          <Stack spacing={0.25} sx={{ mt: 0.25 }}>
                            <Typography variant="body2" fontWeight={600}>
                              {item.label}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {item.description}
                            </Typography>
                          </Stack>
                        }
                      />
                    </Box>
                  ))}
                </Stack>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Stack>
    </Paper>
  );
}
