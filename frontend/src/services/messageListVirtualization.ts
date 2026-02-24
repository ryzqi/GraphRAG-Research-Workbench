export interface MessageListVirtualWindowInput {
  itemHeights: number[];
  scrollTop: number;
  viewportHeight: number;
  overscan: number;
}

export interface MessageListVirtualWindow {
  startIndex: number;
  endIndex: number;
  offsetTop: number;
  offsetBottom: number;
  totalHeight: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function buildPrefixSums(itemHeights: number[]): number[] {
  const prefix = new Array(itemHeights.length + 1);
  prefix[0] = 0;
  for (let i = 0; i < itemHeights.length; i += 1) {
    prefix[i + 1] = prefix[i] + Math.max(1, itemHeights[i] ?? 1);
  }
  return prefix;
}

function findStartIndex(prefixSums: number[], offset: number): number {
  let low = 0;
  let high = prefixSums.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (prefixSums[mid] <= offset) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }
  return Math.max(0, low - 1);
}

export function calculateMessageListVirtualWindow(
  input: MessageListVirtualWindowInput
): MessageListVirtualWindow {
  const { itemHeights, scrollTop, viewportHeight, overscan } = input;
  if (itemHeights.length === 0) {
    return {
      startIndex: 0,
      endIndex: -1,
      offsetTop: 0,
      offsetBottom: 0,
      totalHeight: 0,
    };
  }

  const prefix = buildPrefixSums(itemHeights);
  const totalHeight = prefix[prefix.length - 1];
  const safeScrollTop = clamp(scrollTop, 0, Math.max(0, totalHeight - 1));
  const start = findStartIndex(prefix, safeScrollTop);
  const end = findStartIndex(prefix, safeScrollTop + Math.max(1, viewportHeight));
  const startIndex = clamp(start - overscan, 0, itemHeights.length - 1);
  const endIndex = clamp(end + overscan, startIndex, itemHeights.length - 1);

  return {
    startIndex,
    endIndex,
    offsetTop: prefix[startIndex],
    offsetBottom: totalHeight - prefix[endIndex + 1],
    totalHeight,
  };
}
