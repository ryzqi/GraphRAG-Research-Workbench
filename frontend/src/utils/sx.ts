/**
 * sx 合并工具：
 * - 兼容 sx 为 object / function / array 的各种形式
 * - 避免通过对象展开（...sx）在数组/函数场景下产生异常
 */
import type { SxProps, Theme } from '@mui/material';

type MaybeSx = SxProps<Theme> | undefined | null | false;

export function mergeSx(...values: MaybeSx[]): SxProps<Theme> {
  const result: any[] = [];

  for (const value of values) {
    if (!value) continue;

    if (Array.isArray(value)) {
      result.push(...value);
    } else {
      result.push(value);
    }
  }

  return result;
}
