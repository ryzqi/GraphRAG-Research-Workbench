import { describe, expect, it } from 'vitest';
import { createThinkParser } from './thinkParser';

describe('think parser', () => {
  it('支持 <think> 跨 chunk 解析', () => {
    const parser = createThinkParser();
    const chunks = ['<th', 'ink>思考', '</thi', 'nk>答案'];

    let answer = '';
    let think = '';

    for (const chunk of chunks) {
      const result = parser.feed(chunk);
      answer += result.answerDelta;
      think += result.thinkDelta;
    }

    const flushed = parser.flush();
    answer += flushed.answerDelta;
    think += flushed.thinkDelta;

    expect(think).toBe('思考');
    expect(answer).toBe('答案');
  });
});
