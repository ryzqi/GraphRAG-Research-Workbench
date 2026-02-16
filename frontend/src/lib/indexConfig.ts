import type { IndexConfig } from '../services/knowledgeBases';

interface RangeCheck {
  value: number;
  min: number;
  max: number;
  label: string;
}

function checkRange({ value, min, max, label }: RangeCheck, errors: string[]) {
  if (Number.isNaN(value)) {
    errors.push(`${label} 需要是数字`);
    return;
  }
  if (value < min || value > max) {
    errors.push(`${label} 需在 ${min}~${max} 范围内`);
  }
}

export function validateIndexConfig(config: IndexConfig): string[] {
  const errors: string[] = [];
  const { chunking, contextual } = config;

  // Only validate the currently selected main strategy.
  switch (chunking.general_strategy) {
    case 'query_dependent_multiscale': {
      if (chunking.query_dependent_multiscale.windows.length < 1) {
        errors.push('多尺度滑动窗口分块至少需要 1 个窗口');
        break;
      }

      for (const [idx, window] of chunking.query_dependent_multiscale.windows.entries()) {
        const labelPrefix = `多尺度滑动窗口分块窗口 ${idx + 1}`;
        checkRange(
          {
            value: window.chunk_size_tokens,
            min: 16,
            max: 8000,
            label: `${labelPrefix} chunk_size_tokens`,
          },
          errors
        );
        checkRange(
          {
            value: window.chunk_overlap_tokens,
            min: 0,
            max: 4000,
            label: `${labelPrefix} chunk_overlap_tokens`,
          },
          errors
        );
        if (window.chunk_overlap_tokens >= window.chunk_size_tokens) {
          errors.push(`${labelPrefix} chunk_overlap_tokens 必须小于 chunk_size_tokens`);
        }
      }
      break;
    }
    case 'max_min_semantic': {
      checkRange(
        {
          value: chunking.semantic.min_tokens,
          min: 16,
          max: 1024,
          label: '语义分块 min_tokens',
        },
        errors
      );
      checkRange(
        {
          value: chunking.semantic.max_tokens,
          min: 16,
          max: 2048,
          label: '语义分块 max_tokens',
        },
        errors
      );
      if (chunking.semantic.max_tokens < chunking.semantic.min_tokens) {
        errors.push('语义分块 max_tokens 必须大于等于 min_tokens');
      }
      checkRange(
        {
          value: chunking.semantic.overlap_chars,
          min: 0,
          max: 2000,
          label: '语义分块 overlap_chars',
        },
        errors
      );
      checkRange(
        {
          value: chunking.semantic.embedding_batch_size,
          min: 8,
          max: 1024,
          label: '语义分块 embedding_batch_size',
        },
        errors
      );

      const mode = chunking.semantic.threshold_mode;
      if (mode === 'percentile' || mode === 'hybrid') {
        if (chunking.semantic.breakpoint_percentile == null) {
          errors.push('语义分块 breakpoint_percentile 不能为空');
        } else {
          checkRange(
            {
              value: chunking.semantic.breakpoint_percentile,
              min: 1,
              max: 99,
              label: '语义分块 breakpoint_percentile',
            },
            errors
          );
        }
      }

      if (mode === 'fixed' || mode === 'hybrid') {
        if (chunking.semantic.similarity_threshold == null) {
          errors.push('语义分块相似度阈值不能为空');
        } else {
          checkRange(
            {
              value: chunking.semantic.similarity_threshold,
              min: 0,
              max: 1,
              label: '语义分块相似度阈值',
            },
            errors
          );
        }
      }
      break;
    }
    case 'parent_child':
      checkRange(
        {
          value: chunking.parent_child.parent.chunk_size,
          min: 512,
          max: 20000,
          label: '父块 chunk_size',
        },
        errors
      );
      checkRange(
        {
          value: chunking.parent_child.parent.chunk_overlap,
          min: 0,
          max: 5000,
          label: '父块 chunk_overlap',
        },
        errors
      );
      if (chunking.parent_child.parent.chunk_overlap >= chunking.parent_child.parent.chunk_size) {
        errors.push('父块 chunk_overlap 必须小于父块 chunk_size');
      }
      checkRange(
        {
          value: chunking.parent_child.child.chunk_size,
          min: 128,
          max: 5000,
          label: '子块 chunk_size',
        },
        errors
      );
      checkRange(
        {
          value: chunking.parent_child.child.chunk_overlap,
          min: 0,
          max: 2000,
          label: '子块 chunk_overlap',
        },
        errors
      );
      if (chunking.parent_child.child.chunk_overlap >= chunking.parent_child.child.chunk_size) {
        errors.push('子块 chunk_overlap 必须小于子块 chunk_size');
      }
      if (chunking.parent_child.parent.chunk_size <= chunking.parent_child.child.chunk_size) {
        errors.push('父块 chunk_size 必须大于子块 chunk_size');
      }
      break;
    case 'markdown_heading':
      checkRange(
        {
          value: chunking.markdown_heading.max_heading_level,
          min: 1,
          max: 6,
          label: '标题层级',
        },
        errors
      );
      checkRange(
        {
          value: chunking.markdown_heading.chunk_size,
          min: 200,
          max: 20000,
          label: '章节内 chunk_size',
        },
        errors
      );
      checkRange(
        {
          value: chunking.markdown_heading.chunk_overlap,
          min: 0,
          max: 5000,
          label: '章节内 chunk_overlap',
        },
        errors
      );
      if (chunking.markdown_heading.chunk_overlap >= chunking.markdown_heading.chunk_size) {
        errors.push('章节内 chunk_overlap 必须小于 chunk_size');
      }
      break;
  }

  // Only validate enabled enhancement strategies.
  if (contextual.enabled) {
    checkRange(
      { value: contextual.max_tokens, min: 0, max: 512, label: 'Contextual max_tokens' },
      errors
    );
    if (contextual.max_tokens < 1) {
      errors.push('Contextual 启用时 max_tokens 需大于 0');
    }
    checkRange(
      { value: contextual.concurrency, min: 1, max: 10, label: 'Contextual concurrency' },
      errors
    );
  }

  return errors;
}

