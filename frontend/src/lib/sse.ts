export interface SseEvent {
  event: string;
  data: string;
}

export interface SseParser {
  feed: (chunk: string) => SseEvent[];
  flush: () => SseEvent[];
}

function parseBlock(block: string): SseEvent | null {
  const lines = block.split('\n');
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      event = line.slice(6).trim() || 'message';
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''));
    }
  }

  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join('\n') };
}

export function createSseParser(): SseParser {
  let buffer = '';

  const feed = (chunk: string) => {
    buffer += chunk.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const events: SseEvent[] = [];
    let index = buffer.indexOf('\n\n');
    while (index !== -1) {
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      if (raw.trim()) {
        const event = parseBlock(raw);
        if (event) events.push(event);
      }
      index = buffer.indexOf('\n\n');
    }
    return events;
  };

  const flush = () => {
    const events: SseEvent[] = [];
    if (buffer.trim()) {
      const event = parseBlock(buffer);
      if (event) events.push(event);
    }
    buffer = '';
    return events;
  };

  return { feed, flush };
}

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    for (const event of parser.feed(chunk)) {
      yield event;
    }
  }

  for (const event of parser.flush()) {
    yield event;
  }
}

export function parseSseJson<T>(data: string): T {
  return JSON.parse(data) as T;
}
