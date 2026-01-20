export interface ThinkParseResult {
  answerDelta: string;
  thinkDelta: string;
}

export interface ThinkParser {
  feed: (chunk: string) => ThinkParseResult;
  flush: () => ThinkParseResult;
}

const OPEN_TAG = '<think>';
const CLOSE_TAG = '</think>';

export function createThinkParser(): ThinkParser {
  let buffer = '';
  let inThink = false;

  const process = (text: string): ThinkParseResult => {
    let answerDelta = '';
    let thinkDelta = '';
    let index = 0;

    while (index < text.length) {
      if (!inThink) {
        const openIdx = text.indexOf(OPEN_TAG, index);
        if (openIdx === -1) {
          answerDelta += text.slice(index);
          break;
        }
        answerDelta += text.slice(index, openIdx);
        index = openIdx + OPEN_TAG.length;
        inThink = true;
        continue;
      }
      const closeIdx = text.indexOf(CLOSE_TAG, index);
      if (closeIdx === -1) {
        thinkDelta += text.slice(index);
        break;
      }
      thinkDelta += text.slice(index, closeIdx);
      index = closeIdx + CLOSE_TAG.length;
      inThink = false;
    }

    return { answerDelta, thinkDelta };
  };

  const feed = (chunk: string): ThinkParseResult => {
    const merged = buffer + chunk;

    let tail = '';
    for (const tag of [OPEN_TAG, CLOSE_TAG]) {
      for (let i = tag.length - 1; i >= 1; i -= 1) {
        if (merged.endsWith(tag.slice(0, i))) {
          tail = tag.slice(0, i);
          break;
        }
      }
      if (tail) break;
    }

    const main = tail ? merged.slice(0, -tail.length) : merged;
    buffer = tail;
    return process(main);
  };

  const flush = (): ThinkParseResult => {
    const result = process(buffer);
    buffer = '';
    return result;
  };

  return { feed, flush };
}
