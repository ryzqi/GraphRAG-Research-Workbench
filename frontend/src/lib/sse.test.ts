import { describe, expect, it } from 'vitest';
import { createSseParser } from './sse';

describe('sse parser', () => {
  it('处理 chunk 边界与多行 data', () => {
    const parser = createSseParser();
    const first = parser.feed('event: delta\ndata: {"text":"he');
    expect(first).toHaveLength(0);

    const second = parser.feed('llo"}\n\nevent: update\ndata: line1\ndata: line2\n\n');
    expect(second).toHaveLength(2);
    expect(second[0].event).toBe('delta');
    expect(second[0].data).toBe('{"text":"hello"}');
    expect(second[1].event).toBe('update');
    expect(second[1].data).toBe('line1\nline2');
  });
});
