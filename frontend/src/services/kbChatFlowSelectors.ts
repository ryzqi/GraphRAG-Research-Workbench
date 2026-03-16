import type { ChatNodeDisplayItem, ChatNodeIoEvent } from './chats';

export interface KbChatFlowDetailItem {
  key: string;
  label: string;
  value: string | string[];
}

type DetailSectionKind = 'input' | 'output';

function normalizeDetailItems(
  items: readonly (ChatNodeDisplayItem | KbChatFlowDetailItem)[] | null | undefined
): KbChatFlowDetailItem[] {
  if (!Array.isArray(items) || items.length === 0) {
    return [];
  }

  return items.map((item) => ({
    key: item.key,
    label: item.label,
    value: item.value,
  }));
}

export function selectKbChatFlowDetailItems(params: {
  nodeId: string;
  section: DetailSectionKind;
  items: readonly (ChatNodeDisplayItem | KbChatFlowDetailItem)[] | null | undefined;
  event: ChatNodeIoEvent | null;
}): KbChatFlowDetailItem[] {
  void params.nodeId;
  void params.section;
  void params.event;
  return normalizeDetailItems(params.items);
}
