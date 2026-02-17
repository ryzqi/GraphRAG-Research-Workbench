/**
 * 证据清单组件
 */

import { useCallback, useEffect, useMemo, useState, type SyntheticEvent } from 'react';
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
import {
  buildCitationAnchorId,
  normalizeCitationId,
} from '../services/kbChatCitationAnchors';

interface EvidenceListProps {
  evidence: EvidenceItem[];
  collapseByDefault?: boolean;
  activeCitationId?: string | null;
  onCitationHandled?: (citationId: string) => void;
  citationAnchorScopeId?: string;
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

function normalizeText(value: string | null | undefined): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const text = value.trim();
  return text || null;
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

function getCitationLabelFromLocator(item: EvidenceItem, index: number): string {
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

function getCitationId(item: EvidenceItem, index: number): string {
  const explicit = normalizeCitationId(item.citation_id);
  if (explicit) {
    return explicit;
  }
  return `S${index + 1}`;
}

function getCitationChipLabel(item: EvidenceItem, index: number): string {
  const citationId = normalizeCitationId(item.citation_id);
  if (citationId) {
    return `[${citationId}]`;
  }
  return getCitationLabelFromLocator(item, index);
}

function getCitationAnchorId(citationId: string, scopeId?: string): string {
  return buildCitationAnchorId(citationId, scopeId);
}

function getCitationPageHint(item: EvidenceItem): string | null {
  const explicit = normalizeText(item.citation_page_hint);
  if (explicit) {
    return explicit;
  }
  const locator = item.locator;
  if (!locator || typeof locator !== 'object') {
    return null;
  }
  const pageStart = locator.page_start;
  const pageEnd = locator.page_end;
  if (typeof pageStart === 'number' && pageStart > 0) {
    if (typeof pageEnd === 'number' && pageEnd > 0 && pageEnd !== pageStart) {
      return `p.${pageStart}-${pageEnd}`;
    }
    return `p.${pageStart}`;
  }
  if (typeof pageEnd === 'number' && pageEnd > 0) {
    return `p.${pageEnd}`;
  }
  return null;
}

function getSourceTitle(item: EvidenceItem, index: number): string {
  const citationTitle = normalizeText(item.citation_title);
  if (citationTitle) {
    return citationTitle;
  }

  const locatorMaterialTitle = normalizeText(getLocatorString(item.locator, 'material_title'));
  if (locatorMaterialTitle) {
    return locatorMaterialTitle;
  }

  return getCitationLabelFromLocator(item, index);
}

/**
 * 生成证据项的唯一 key
 */
function getEvidenceKey(item: EvidenceItem, index: number): string {
  const citationId = normalizeCitationId(item.citation_id);
  if (citationId) {
    return `citation-${citationId}`;
  }
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

interface EvidenceDisplayItem {
  key: string;
  item: EvidenceItem;
  citationId: string;
  citationChipLabel: string;
  sourceTitle: string;
  pageHint: string | null;
}

function createDefaultExpandedIds(
  items: EvidenceDisplayItem[],
  collapseByDefault: boolean
): Set<string> {
  if (collapseByDefault) {
    return new Set();
  }
  return new Set(items.map((item) => item.citationId));
}

export function EvidenceList({
  evidence,
  collapseByDefault = true,
  activeCitationId,
  onCitationHandled,
  citationAnchorScopeId,
}: EvidenceListProps) {
  const displayItems = useMemo<EvidenceDisplayItem[]>(
    () =>
      evidence.map((item, index) => {
        const citationId = getCitationId(item, index);
        return {
          key: getEvidenceKey(item, index),
          item,
          citationId,
          citationChipLabel: getCitationChipLabel(item, index),
          sourceTitle: getSourceTitle(item, index),
          pageHint: getCitationPageHint(item),
        };
      }),
    [evidence]
  );

  const [expandedCitationIds, setExpandedCitationIds] = useState<Set<string>>(() =>
    createDefaultExpandedIds(displayItems, collapseByDefault)
  );

  useEffect(() => {
    setExpandedCitationIds(createDefaultExpandedIds(displayItems, collapseByDefault));
  }, [collapseByDefault, displayItems]);

  const normalizedActiveCitationId = useMemo(
    () => normalizeCitationId(activeCitationId),
    [activeCitationId]
  );

  useEffect(() => {
    if (!normalizedActiveCitationId) {
      return;
    }
    const target = displayItems.find((item) => item.citationId === normalizedActiveCitationId);
    if (!target) {
      return;
    }

    setExpandedCitationIds((prev) => {
      if (prev.has(normalizedActiveCitationId)) {
        return prev;
      }
      const next = new Set(prev);
      next.add(normalizedActiveCitationId);
      return next;
    });

    if (typeof window !== 'undefined') {
      window.requestAnimationFrame(() => {
        const element = document.getElementById(
          getCitationAnchorId(normalizedActiveCitationId, citationAnchorScopeId)
        );
        element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }
    onCitationHandled?.(normalizedActiveCitationId);
  }, [citationAnchorScopeId, displayItems, normalizedActiveCitationId, onCitationHandled]);

  const handleAccordionChange = useCallback(
    (citationId: string) =>
      (_event: SyntheticEvent, expanded: boolean) => {
        setExpandedCitationIds((prev) => {
          const next = new Set(prev);
          if (expanded) {
            next.add(citationId);
          } else {
            next.delete(citationId);
          }
          return next;
        });
      },
    []
  );

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
      {displayItems.map((entry) => (
        <Accordion
          id={getCitationAnchorId(entry.citationId, citationAnchorScopeId)}
          disableGutters
          elevation={0}
          key={entry.key}
          expanded={expandedCitationIds.has(entry.citationId)}
          onChange={handleAccordionChange(entry.citationId)}
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
              label={entry.citationChipLabel}
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
              {entry.item.source_kind === 'kb' ? '知识库' : '外部来源'}
              {entry.sourceTitle ? ` · ${entry.sourceTitle}` : null}
              {entry.pageHint ? ` · ${entry.pageHint}` : null}
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
              {entry.item.excerpt}
            </Typography>
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  );
}
