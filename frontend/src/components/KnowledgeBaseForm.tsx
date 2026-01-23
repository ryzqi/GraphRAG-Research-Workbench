/**
 * 知识库表单组件（创建/编辑）
 */
import { useState } from 'react';
import { Box, Divider, Stack, TextField, Typography } from '@mui/material';
import { Button } from './ui/Button';
import { ErrorAlert } from './ui/ErrorAlert';
import { getErrorMessage } from '../lib/errorHandler';
import { IndexConfigForm } from './IndexConfigForm';
import { validateIndexConfig } from '../lib/indexConfig';
import {
  createDefaultIndexConfig,
  type KnowledgeBase,
  type KnowledgeBaseCreate,
  type KnowledgeBaseUpdate,
  type IndexConfig,
} from '../services/knowledgeBases';

type KnowledgeBaseFormProps =
  | {
      mode: 'create';
      onSubmit: (data: KnowledgeBaseCreate) => Promise<void>;
      onCancel: () => void;
      loading?: boolean;
    }
  | {
      mode: 'edit';
      initialData: KnowledgeBase;
      onSubmit: (data: KnowledgeBaseUpdate) => Promise<void>;
      onCancel: () => void;
      loading?: boolean;
    };

export function KnowledgeBaseForm(props: KnowledgeBaseFormProps) {
  const { mode, onCancel, loading = false } = props;
  const initialData = mode === 'edit' ? props.initialData : undefined;

  const [name, setName] = useState(initialData?.name ?? '');
  const [description, setDescription] = useState(initialData?.description ?? '');
  const [tagsInput, setTagsInput] = useState(initialData?.tags?.join(', ') ?? '');
  const [indexConfig, setIndexConfig] = useState<IndexConfig>(
    initialData?.index_config ?? createDefaultIndexConfig()
  );
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError('名称不能为空');
      return;
    }

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      if (props.mode === 'create') {
        const validationErrors = validateIndexConfig(indexConfig);
        if (validationErrors.length > 0) {
          setError(`索引配置校验失败：${validationErrors.join('；')}`);
          return;
        }
        const payload: KnowledgeBaseCreate = {
          name: name.trim(),
          description: description.trim() || undefined,
          tags: tags.length > 0 ? tags : undefined,
          index_config: indexConfig,
        };
        await props.onSubmit(payload);
      } else {
        const payload: KnowledgeBaseUpdate = {
          name: name.trim(),
          description: description.trim() || undefined,
          tags: tags.length > 0 ? tags : undefined,
        };
        await props.onSubmit(payload);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <Box component="form" onSubmit={handleSubmit}>
      <ErrorAlert error={error} sx={{ mb: 2 }} />

      <Stack spacing={2.5}>
        <TextField
          label="名称"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="输入知识库名称"
          inputProps={{ maxLength: 64 }}
          disabled={loading}
          fullWidth
        />

        <TextField
          label="描述"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="输入知识库描述（可选）"
          inputProps={{ maxLength: 500 }}
          multiline
          rows={3}
          disabled={loading}
          fullWidth
        />

        <TextField
          label="标签"
          value={tagsInput}
          onChange={(e) => setTagsInput(e.target.value)}
          placeholder="用逗号分隔多个标签"
          helperText="例如：技术文档, API, 教程"
          disabled={loading}
          fullWidth
        />

        {mode === 'create' && (
          <>
            <Divider />
            <Typography variant="h6">索引配置</Typography>
            <IndexConfigForm value={indexConfig} onChange={setIndexConfig} disabled={loading} />
          </>
        )}
      </Stack>

      <Stack direction="row" spacing={1.5} justifyContent="flex-end" sx={{ mt: 3 }}>
        <Button variant="outlined" onClick={onCancel} disabled={loading}>
          取消
        </Button>
        <Button type="submit" variant="contained" loading={loading}>
          {mode === 'create' ? '创建' : '保存'}
        </Button>
      </Stack>
    </Box>
  );
}
