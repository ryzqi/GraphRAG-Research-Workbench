/**
 * 证据清单组件
 */

import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Chip,
  Stack,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import type { EvidenceItem } from '../services/chats';

interface EvidenceListProps {
  evidence: EvidenceItem[];
  collapseByDefault?: boolean;
}

/**
 * 从 locator 中安全读取 string 字段（避免 unknown 直接渲染到 JSX）
 */
function getLocatorString(
  locator: Record<string, unknown> | null | undefined,
  key: string
): string | null {
  const value = locator?.[key];
  return typeof value === 'string' ? value : null;
}

function stripExtension(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) {
    return '';
  }
  const normalized = trimmed.replace(/\\/g, '/');
  const base = normalized.split('/').pop() ?? normalized;
  const dotIndex = base.lastIndexOf('.');
  if (dotIndex <= 0) {
    return base;
  }
  return base.slice(0, dotIndex);
}

function getCitationLabel(item: EvidenceItem, index: number): string {
  const explicit = getLocatorString(item.locator, 'citation_label');
  if (explicit && explicit.trim()) {
    return explicit.trim();
  }
  const filename = getLocatorString(item.locator, 'filename');
  if (filename && filename.trim()) {
    const stem = stripExtension(filename);
    if (stem.trim()) {
      return stem.trim();
    }
  }
  return `资料${index + 1}`;
}

/**
 * 生成证据项的唯一 key
 */
function getEvidenceKey(item: EvidenceItem, index: number): string {
  // 优先使用 locator 中的 chunk_id
  const chunkId = getLocatorString(item.locator, 'chunk_id');
  if (chunkId) {
    return `chunk-${chunkId}`;
  }
  // 其次使用 kb_id + material_id 组合
  if (item.kb_id && item.material_id) {
    return `kb-${item.kb_id}-mat-${item.material_id}-${index}`;
  }
  // 最后使用 excerpt 的 hash 作为 key
  const excerptHash = item.excerpt.slice(0, 50).replace(/\s+/g, '-');
  return `${item.source_kind}-${excerptHash}-${index}`;
}

export function EvidenceList({ evidence, collapseByDefault = true }: EvidenceListProps) {
  if (evidence.length === 0) {
    return (
      <Typography variant='body2' color='text.secondary' sx={{ py: 1 }}>
        暂无相关证据
      </Typography>
    );
  }

  return (
    <Stack spacing={1}>
      <Typography variant='body2' fontWeight={600} color='text.primary'>
        参考来源 ({evidence.length})
      </Typography>
      {evidence.map((item, index) => {
        const materialTitle = getLocatorString(item.locator, 'material_title');
        const citationLabel = getCitationLabel(item, index);

        return (
          <Accordion
            disableGutters
            elevation={0}
            key={getEvidenceKey(item, index)}
            defaultExpanded={!collapseByDefault}
            sx={{
              borderRadius: 2,
              border: 1,
              borderColor: 'divider',
              bgcolor: (theme) =>
                theme.palette.mode === 'light'
                  ? alpha(theme.palette.background.paper, 0.86)
                  : alpha(theme.palette.background.paper, 0.56),
              '&::before': { display: 'none' },
            }}
          >
            <AccordionSummary
              expandIcon={<ExpandMoreIcon fontSize='small' />}
              sx={{
                px: 1.5,
                py: 0.5,
                minHeight: 'unset',
                '& .MuiAccordionSummary-content': {
                  my: 0.25,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  flexWrap: 'wrap',
                },
                '& .MuiAccordionSummary-expandIconWrapper': {
                  color: 'text.secondary',
                },
              }}
            >
              <Chip
                size='small'
                label={citationLabel}
                sx={{
                  borderRadius: 999,
                  bgcolor: (theme) =>
                    theme.palette.mode === 'light'
                      ? alpha(theme.palette.primary.main, 0.12)
                      : alpha(theme.palette.primary.main, 0.28),
                  color: 'primary.main',
                  border: 1,
                  borderColor: (theme) => alpha(theme.palette.primary.main, 0.28),
                  fontWeight: 600,
                }}
              />
              <Typography variant='caption' color='text.secondary'>
                {item.source_kind === 'kb' ? '知识库' : '外部来源'}
                {materialTitle ? ` · ${materialTitle}` : null}
              </Typography>
            </AccordionSummary>
            <AccordionDetails sx={{ px: 1.5, pt: 0, pb: 1.25 }}>
              <Typography
                variant='body2'
                sx={{
                  color: 'text.primary',
                  lineHeight: 1.65,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {item.excerpt}
              </Typography>
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Stack>
  );
}
