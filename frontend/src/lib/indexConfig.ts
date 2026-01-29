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
  const { chunking, contextual, retrieval } = config;

  // Only validate the currently selected main strategy.
  switch (chunking.general_strategy) {
    case 'sliding_window':
      checkRange(
        {
          value: chunking.sliding_window.chunk_size,
          min: 128,
          max: 20000,
          label: '滑动窗口 chunk_size',
        },
        errors
      );
      checkRange(
        {
          value: chunking.sliding_window.chunk_overlap,
          min: 0,
          max: 2000,
          label: '滑动窗口 overlap',
        },
        errors
      );
      if (chunking.sliding_window.chunk_overlap >= chunking.sliding_window.chunk_size) {
        errors.push('滑动窗口 overlap 必须小于 chunk_size');
      }
      break;
    case 'max_min_semantic':
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
          value: chunking.semantic.similarity_threshold,
          min: 0,
          max: 1,
          label: '语义分块相似度阈值',
        },
        errors
      );
      checkRange(
        {
          value: chunking.semantic.overlap_chars,
          min: 0,
          max: 2000,
          label: '语义分块 overlap_chars',
        },
        errors
      );
      break;
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
          label: '父块 overlap',
        },
        errors
      );
      if (chunking.parent_child.parent.chunk_overlap >= chunking.parent_child.parent.chunk_size) {
        errors.push('父块 overlap 必须小于父块 chunk_size');
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
          label: '子块 overlap',
        },
        errors
      );
      if (chunking.parent_child.child.chunk_overlap >= chunking.parent_child.child.chunk_size) {
        errors.push('子块 overlap 必须小于子块 chunk_size');
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
      { value: contextual.timeout_seconds, min: 1, max: 60, label: 'Contextual 超时' },
      errors
    );
    checkRange(
      { value: contextual.max_tokens, min: 0, max: 512, label: 'Contextual max_tokens' },
      errors
    );
    if (contextual.max_tokens < 1) {
      errors.push('Contextual 启用时 max_tokens 需大于 0');
    }
    checkRange(
      { value: contextual.concurrency, min: 1, max: 10, label: 'Contextual 并发' },
      errors
    );
  }

  if (retrieval.parent_child.enabled) {
    checkRange(
      { value: retrieval.parent_child.max_parents, min: 1, max: 20, label: '父子检索 max_parents' },
      errors
    );
    checkRange(
      {
        value: retrieval.parent_child.max_children_per_parent,
        min: 1,
        max: 10,
        label: '父子检索 max_children_per_parent',
      },
      errors
    );
  }

  return errors;
}
