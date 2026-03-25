/**
 * 结构化流式增量解析器
 * 对齐 LangChain 消息内容块格式，替代旧版 thinkParser
 */

/** 增量类型枚举 */
export type DeltaKind = 'thinking' | 'answer' | 'tool_call' | 'tool_result' | 'attachment';

/** 结构化流式增量 */
export interface StreamDelta {
  kind: DeltaKind;
  content?: string;
  tool_call_id?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_output?: string;
  attachment_type?: string;
  attachment_url?: string;
  attachment_mime?: string;
}

/** 消息状态（对应文档里的 MessageState） */
export interface MessageState {
  status: 'streaming' | 'completed' | 'error';
  thought_log: string;
  tool_steps: ToolStep[];
  final_content: string;
  is_thought_expanded: boolean;
}

/** 工具步骤 */
export interface ToolStep {
  tool_call_id?: string;
  tool_name: string;
  tool_args?: Record<string, unknown>;
  tool_output?: string;
  status: 'pending' | 'completed' | 'failed';
}

/** 创建初始消息状态 */
export function createMessageState(): MessageState {
  return {
    status: 'streaming',
    thought_log: '',
    tool_steps: [],
    final_content: '',
    is_thought_expanded: true,
  };
}

/** 应用 delta 到消息状态 */
export function applyDelta(state: MessageState, delta: StreamDelta): MessageState {
  const newState = { ...state };

  switch (delta.kind) {
    case 'thinking':
      newState.thought_log += delta.content ?? '';
      break;

    case 'answer':
      newState.final_content += delta.content ?? '';
      break;

    case 'tool_call':
      // 追加新的工具调用步骤。
      newState.tool_steps = [
        ...newState.tool_steps,
        {
          tool_call_id: delta.tool_call_id,
          tool_name: delta.tool_name ?? 'unknown',
          tool_args: delta.tool_args,
          status: 'pending',
        },
      ];
      break;

    case 'tool_result':
      // 更新对应工具调用的执行结果。
      newState.tool_steps = newState.tool_steps.map((step) => {
        if (step.tool_call_id === delta.tool_call_id || step.tool_name === delta.tool_name) {
          return {
            ...step,
            tool_output: delta.tool_output,
            status: 'completed' as const,
          };
        }
        return step;
      });
      break;

    case 'attachment':
      // 附件暂时以占位文本形式追加到内容中。
      if (delta.attachment_type && delta.attachment_url) {
        newState.final_content += `\n[${delta.attachment_type}: ${delta.attachment_url}]\n`;
      }
      break;
  }

  return newState;
}

/** 完成消息状态 */
export function completeMessageState(state: MessageState): MessageState {
  return {
    ...state,
    status: 'completed',
    is_thought_expanded: false, // 完成后默认收起思考过程
  };
}

/** 解析 SSE delta 数据 */
export function parseDelta(data: unknown): StreamDelta | null {
  if (!data || typeof data !== 'object') {
    return null;
  }

  const obj = data as Record<string, unknown>;
  const kind = obj.kind as DeltaKind | undefined;

  // 兼容旧格式：缺少 kind 但存在 text 时，按 answer 处理。
  if (!kind && typeof obj.text === 'string') {
    return {
      kind: 'answer',
      content: obj.text,
    };
  }

  if (!kind) {
    return null;
  }

  return {
    kind,
    content: typeof obj.content === 'string' ? obj.content : undefined,
    tool_call_id: typeof obj.tool_call_id === 'string' ? obj.tool_call_id : undefined,
    tool_name: typeof obj.tool_name === 'string' ? obj.tool_name : undefined,
    tool_args: obj.tool_args as Record<string, unknown> | undefined,
    tool_output: typeof obj.tool_output === 'string' ? obj.tool_output : undefined,
    attachment_type: typeof obj.attachment_type === 'string' ? obj.attachment_type : undefined,
    attachment_url: typeof obj.attachment_url === 'string' ? obj.attachment_url : undefined,
    attachment_mime: typeof obj.attachment_mime === 'string' ? obj.attachment_mime : undefined,
  };
}
