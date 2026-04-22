/**
 * 统一 manifest 输入编辑器（text/url/file）
 */

import { useMemo } from 'react';
import {
  Alert,
  Box,
  Chip,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import AddIcon from '@mui/icons-material/Add';
import type { ManifestSourceType } from '../services/ingestionBatches';
import type { PublicRuntimeConfigRead } from '../services/runtimeConfig';
import {
  getAcceptedFileTypes,
  getSupportedFileTypesLabel,
  validateFile,
} from '../utils/fileValidation';
import { Button } from './ui/Button';

type DraftSourceType = ManifestSourceType;

interface DraftBaseEntry {
  id: string;
  sourceType: DraftSourceType;
  title: string;
}

export interface DraftTextEntry extends DraftBaseEntry {
  sourceType: 'text';
  text: string;
}

export interface DraftUrlEntry extends DraftBaseEntry {
  sourceType: 'url';
  url: string;
}

export interface DraftFileEntry extends DraftBaseEntry {
  sourceType: 'file';
  file: File | null;
}

export type ManifestDraftEntry = DraftTextEntry | DraftUrlEntry | DraftFileEntry;

export interface NormalizedTextDraftEntry {
  id: string;
  sourceType: 'text';
  title?: string;
  text: string;
}

export interface NormalizedUrlDraftEntry {
  id: string;
  sourceType: 'url';
  title?: string;
  url: string;
}

export interface NormalizedFileDraftEntry {
  id: string;
  sourceType: 'file';
  title?: string;
  file: File;
}

export type NormalizedManifestDraftEntry =
  | NormalizedTextDraftEntry
  | NormalizedUrlDraftEntry
  | NormalizedFileDraftEntry;

export interface ManifestDraftValidation {
  globalErrors: string[];
  entryErrors: Record<string, string[]>;
  normalizedValidEntries: NormalizedManifestDraftEntry[];
}

interface IngestionManifestEditorProps {
  entries: ManifestDraftEntry[];
  onChange: (entries: ManifestDraftEntry[]) => void;
  validation?: ManifestDraftValidation;
  serverEntryErrors?: Record<string, string[]>;
  disabled?: boolean;
  markdownOnly?: boolean;
  runtimeConfig?: PublicRuntimeConfigRead | null;
}

function newEntryId(prefix: DraftSourceType): string {
  if (globalThis.crypto?.randomUUID) {
    return prefix + '_' + globalThis.crypto.randomUUID();
  }
  return prefix + '_' + Date.now() + '_' + Math.random().toString(16).slice(2);
}

function sourceLabel(sourceType: DraftSourceType): string {
  switch (sourceType) {
    case 'text':
      return '文本';
    case 'url':
      return 'URL';
    case 'file':
      return '文件';
    default:
      return sourceType;
  }
}

function isHttpUrl(raw: string): boolean {
  try {
    const url = new URL(raw);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function extOf(fileName: string): string {
  const index = fileName.lastIndexOf('.');
  if (index === -1) {
    return '';
  }
  return fileName.slice(index).toLowerCase();
}

function dedupeStrings(values: string[]): string[] {
  return Array.from(new Set(values));
}

export function createEmptyManifestEntry(sourceType: DraftSourceType): ManifestDraftEntry {
  if (sourceType === 'text') {
    return {
      id: newEntryId(sourceType),
      sourceType,
      title: '',
      text: '',
    };
  }

  if (sourceType === 'url') {
    return {
      id: newEntryId(sourceType),
      sourceType,
      title: '',
      url: '',
    };
  }

  return {
    id: newEntryId(sourceType),
    sourceType,
    title: '',
    file: null,
  };
}

export function validateManifestDraftEntries(
  entries: ManifestDraftEntry[],
  opts?: { markdownOnly?: boolean; runtimeConfig?: PublicRuntimeConfigRead | null }
): ManifestDraftValidation {
  const markdownOnly = opts?.markdownOnly ?? false;
  const runtimeConfig = opts?.runtimeConfig;
  const manifestConstraints = runtimeConfig?.ingestion_manifest_constraints ?? null;
  const globalErrors: string[] = [];
  const entryErrors: Record<string, string[]> = {};
  const normalizedValidEntries: NormalizedManifestDraftEntry[] = [];
  let urlCount = 0;
  let fileCount = 0;

  if (manifestConstraints && entries.length > manifestConstraints.max_entries) {
    globalErrors.push(
      '单批次最多 ' + manifestConstraints.max_entries + ' 个条目（当前 ' + entries.length + '）'
    );
  }

  for (const entry of entries) {
    const currentErrors: string[] = [];
    const title = entry.title.trim();

    if (entry.sourceType === 'text') {
      const text = entry.text.trim();
      if (!text) {
        currentErrors.push('文本内容不能为空');
      }
      if (manifestConstraints && text.length > manifestConstraints.max_text_length) {
        currentErrors.push('文本长度不能超过 ' + manifestConstraints.max_text_length + ' 字符');
      }
      if (currentErrors.length === 0) {
        normalizedValidEntries.push({
          id: entry.id,
          sourceType: 'text',
          title: title || undefined,
          text,
        });
      }
    }

    if (entry.sourceType === 'url') {
      urlCount += 1;
      const url = entry.url.trim();
      if (!url) {
        currentErrors.push('URL 不能为空');
      } else if (!isHttpUrl(url)) {
        currentErrors.push('URL 仅支持 http/https 协议');
      }
      if (currentErrors.length === 0) {
        normalizedValidEntries.push({
          id: entry.id,
          sourceType: 'url',
          title: title || undefined,
          url,
        });
      }
    }

    if (entry.sourceType === 'file') {
      fileCount += 1;
      if (!entry.file) {
        currentErrors.push('请选择文件');
      } else {
        const result = validateFile(entry.file, runtimeConfig);
        if (!result.valid) {
          currentErrors.push(result.error ?? '文件校验失败');
        }
        if (markdownOnly && extOf(entry.file.name) !== '.md') {
          currentErrors.push('当前配置仅支持 .md 文件');
        }
      }

      if (currentErrors.length === 0 && entry.file) {
        normalizedValidEntries.push({
          id: entry.id,
          sourceType: 'file',
          title: title || undefined,
          file: entry.file,
        });
      }
    }

    if (currentErrors.length > 0) {
      entryErrors[entry.id] = dedupeStrings(currentErrors);
    }
  }

  if (manifestConstraints && urlCount > manifestConstraints.max_url_entries) {
    globalErrors.push(
      '单批次 URL 条目不能超过 ' +
        manifestConstraints.max_url_entries +
        ' 个（当前 ' +
        urlCount +
        '）'
    );
  }

  if (manifestConstraints && fileCount > manifestConstraints.max_file_entries) {
    globalErrors.push(
      '单批次文件条目不能超过 ' +
        manifestConstraints.max_file_entries +
        ' 个（当前 ' +
        fileCount +
        '）'
    );
  }

  return {
    globalErrors: dedupeStrings(globalErrors),
    entryErrors,
    normalizedValidEntries,
  };
}

export function IngestionManifestEditor({
  entries,
  onChange,
  validation,
  serverEntryErrors,
  disabled = false,
  markdownOnly = false,
  runtimeConfig,
}: IngestionManifestEditorProps) {
  const mergedEntryErrors = useMemo(() => {
    const merged: Record<string, string[]> = {};

    const allIds = new Set<string>([
      ...Object.keys(validation?.entryErrors ?? {}),
      ...Object.keys(serverEntryErrors ?? {}),
    ]);

    for (const id of allIds) {
      const localErrors = validation?.entryErrors[id] ?? [];
      const remoteErrors = serverEntryErrors?.[id] ?? [];
      const errors = dedupeStrings([...localErrors, ...remoteErrors]);
      if (errors.length > 0) {
        merged[id] = errors;
      }
    }

    return merged;
  }, [validation?.entryErrors, serverEntryErrors]);

  const updateEntry = (nextEntry: ManifestDraftEntry) => {
    onChange(entries.map((entry) => (entry.id === nextEntry.id ? nextEntry : entry)));
  };

  const removeEntry = (id: string) => {
    onChange(entries.filter((entry) => entry.id !== id));
  };

  const addEntry = (sourceType: DraftSourceType) => {
    onChange([...entries, createEmptyManifestEntry(sourceType)]);
  };

  const hasGlobalErrors = (validation?.globalErrors.length ?? 0) > 0;

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25}>
        <Button
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={() => addEntry('text')}
          disabled={disabled}
        >
          添加文本
        </Button>
        <Button
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={() => addEntry('url')}
          disabled={disabled}
        >
          添加 URL
        </Button>
        <Button
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={() => addEntry('file')}
          disabled={disabled}
        >
          添加文件
        </Button>
      </Stack>

      {hasGlobalErrors && (
        <Alert severity="warning" variant="outlined">
          {validation?.globalErrors.join('；')}
        </Alert>
      )}

      {entries.length === 0 && (
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Typography color="text.secondary">
            还没有待提交条目。请添加文本、URL 或文件。
          </Typography>
        </Paper>
      )}

      {entries.map((entry) => {
        const currentErrors = mergedEntryErrors[entry.id] ?? [];
        return (
          <Paper key={entry.id} variant="outlined" sx={{ p: 2 }}>
            <Stack spacing={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Chip
                  label={sourceLabel(entry.sourceType)}
                  size="small"
                  color="primary"
                  variant="outlined"
                />
                <IconButton
                  aria-label="删除条目"
                  onClick={() => removeEntry(entry.id)}
                  disabled={disabled}
                  size="small"
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>

              <TextField
                label="标题（可选）"
                value={entry.title}
                onChange={(e) => updateEntry({ ...entry, title: e.target.value })}
                disabled={disabled}
                fullWidth
              />

              {entry.sourceType === 'text' && (
                <TextField
                  label="文本内容"
                  value={entry.text}
                  onChange={(e) => updateEntry({ ...entry, text: e.target.value })}
                  disabled={disabled}
                  multiline
                  minRows={4}
                  fullWidth
                />
              )}

              {entry.sourceType === 'url' && (
                <TextField
                  label="URL"
                  placeholder="https://example.com"
                  value={entry.url}
                  onChange={(e) => updateEntry({ ...entry, url: e.target.value })}
                  disabled={disabled}
                  fullWidth
                />
              )}

              {entry.sourceType === 'file' && (
                <Stack spacing={1}>
                  <Box>
                    <input
                      type="file"
                      accept={markdownOnly ? '.md' : getAcceptedFileTypes(runtimeConfig)}
                      onChange={(e) => {
                        const file = e.target.files?.[0] ?? null;
                        updateEntry({ ...entry, file });
                      }}
                      disabled={disabled || !runtimeConfig}
                    />
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    {!runtimeConfig
                      ? '正在加载上传策略…'
                      : markdownOnly
                      ? '当前配置仅支持 .md 文件'
                      : `支持 ${getSupportedFileTypesLabel(runtimeConfig)}`}
                  </Typography>
                  {entry.file && (
                    <Typography variant="body2" color="text.secondary">
                      已选择：{entry.file.name}（{Math.max(1, Math.round(entry.file.size / 1024))} KB）
                    </Typography>
                  )}
                </Stack>
              )}

              {currentErrors.length > 0 && (
                <Alert severity="error" variant="outlined">
                  {currentErrors.join('；')}
                </Alert>
              )}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}
