import { parseSseStream, type SseEvent } from '../lib/sse';
import {
  ApiConfigurationError,
  buildApiRequestContext,
  buildBackendConnectivityHint,
  HttpError,
} from './http';

export async function openSseStream(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  const headers = new Headers(init.headers ?? {});
  headers.set('Accept', 'text/event-stream');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let requestContext: ReturnType<typeof buildApiRequestContext>;
  try {
    requestContext = buildApiRequestContext(path);
  } catch (error) {
    if (error instanceof ApiConfigurationError) {
      throw new HttpError(`${error.message} 请求：${path}`, 500, {
        body: error.message,
      });
    }
    throw error;
  }

  let res: Response;
  try {
    res = await fetch(requestContext.url, {
      ...init,
      headers,
      signal,
    });
  } catch (err) {
    if (signal?.aborted || (err as { name?: string } | undefined)?.name === 'AbortError') {
      throw new HttpError('请求已取消', 499, { body: err instanceof Error ? err.message : err });
    }
    throw new HttpError(buildBackendConnectivityHint(requestContext), 0, {
      body: err instanceof Error ? err.message : err,
    });
  }

  if (!res.ok) {
    const text = await res.text();
    let body: unknown = undefined;
    try {
      body = text ? (JSON.parse(text) as unknown) : undefined;
    } catch {
      body = text;
    }
    const message = (body as any)?.error?.message ?? `请求失败（${res.status}）`;
    throw new HttpError(message, res.status, { body });
  }

  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('text/event-stream')) {
    throw new Error('服务端未返回 SSE 流');
  }
  if (!res.body) {
    throw new Error('响应没有可读数据流');
  }

  return parseSseStream(res.body);
}
