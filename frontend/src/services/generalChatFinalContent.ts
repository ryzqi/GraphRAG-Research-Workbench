interface ResolveGeneralChatFinalContentArgs {
  streamedContent: string;
  finalContent: string;
}

export function resolveGeneralChatFinalContent({
  streamedContent,
  finalContent,
}: ResolveGeneralChatFinalContentArgs): string {
  return finalContent.trim() ? finalContent : streamedContent;
}
