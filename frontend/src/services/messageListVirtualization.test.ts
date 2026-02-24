import { describe, expect, it } from 'vitest';

import { calculateMessageListVirtualWindow } from './messageListVirtualization';

describe('calculateMessageListVirtualWindow', () => {
  it('limits rendered range for large list near top', () => {
    const window = calculateMessageListVirtualWindow({
      itemHeights: new Array(200).fill(100),
      scrollTop: 0,
      viewportHeight: 500,
      overscan: 2,
    });

    expect(window.startIndex).toBe(0);
    expect(window.endIndex).toBe(7);
    expect(window.offsetTop).toBe(0);
    expect(window.offsetBottom).toBe(19200);
  });

  it('moves window with scroll position', () => {
    const window = calculateMessageListVirtualWindow({
      itemHeights: new Array(200).fill(100),
      scrollTop: 5000,
      viewportHeight: 500,
      overscan: 2,
    });

    expect(window.startIndex).toBe(48);
    expect(window.endIndex).toBe(57);
    expect(window.offsetTop).toBe(4800);
    expect(window.offsetBottom).toBe(14200);
  });

  it('keeps streaming-tail rendering bounded near bottom', () => {
    const heights = new Array(200).fill(100);
    heights[199] = 360;

    const window = calculateMessageListVirtualWindow({
      itemHeights: heights,
      scrollTop: 19800,
      viewportHeight: 600,
      overscan: 3,
    });

    expect(window.startIndex).toBeGreaterThan(185);
    expect(window.endIndex).toBe(199);
    expect(window.endIndex - window.startIndex + 1).toBeLessThanOrEqual(13);
  });
});
