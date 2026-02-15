import { describe, expect, it } from 'vitest';

import { stripTrailingReferenceSection } from '../lib/kbChatContent';

describe('stripTrailingReferenceSection', () => {
  it('removes a trailing markdown reference section', () => {
    const content = [
      '这是回答正文。',
      '',
      '## 参考来源 (2)',
      '- [S1] Agent基础',
      '- [S2] image.png',
    ].join('\n');

    expect(stripTrailingReferenceSection(content)).toBe('这是回答正文。');
  });

  it('removes a trailing inline reference line', () => {
    const content = ['第一段', '第二段', '参考来源： [S1] Agent基础'].join('\n');

    expect(stripTrailingReferenceSection(content)).toBe(['第一段', '第二段'].join('\n'));
  });

  it('keeps content unchanged when reference label appears in non-trailing position', () => {
    const content = ['参考来源： [S1] Agent基础', '', '这里是正文，说明仍在继续。'].join('\n');

    expect(stripTrailingReferenceSection(content)).toBe(content);
  });
});
