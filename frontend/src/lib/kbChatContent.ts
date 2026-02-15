function isReferenceHeadingLine(line: string): boolean {
  return /^(?:#{1,6}\s*)?参考来源(?:\s*\(\d+\))?\s*$/.test(line);
}

function isInlineReferenceLine(line: string): boolean {
  return /^参考来源\s*[：:].*$/.test(line);
}

function isLikelyReferenceBodyLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) {
    return true;
  }
  return (
    /^[-*+]\s+/.test(trimmed) ||
    /^\d+[.)、]\s+/.test(trimmed) ||
    /^\[?S\d+\]?/i.test(trimmed) ||
    /^资料\d+/.test(trimmed) ||
    /^https?:\/\//i.test(trimmed)
  );
}

export function stripTrailingReferenceSection(content: string): string {
  if (!content.trim()) {
    return content;
  }

  const normalized = content.replace(/\r\n/g, '\n');
  const lines = normalized.split('\n');
  let referenceStart = -1;

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const trimmed = lines[index].trim();
    if (!trimmed) {
      continue;
    }
    if (isReferenceHeadingLine(trimmed) || isInlineReferenceLine(trimmed)) {
      referenceStart = index;
      break;
    }
  }

  if (referenceStart === -1) {
    return content;
  }

  const isInline = isInlineReferenceLine(lines[referenceStart].trim());
  const tailLines = lines.slice(referenceStart + 1);
  const hasTailContent = tailLines.some((line) => line.trim().length > 0);

  if (isInline && hasTailContent) {
    return content;
  }

  if (!isInline && hasTailContent && !tailLines.every(isLikelyReferenceBodyLine)) {
    return content;
  }

  const trailingThreshold = Math.floor(lines.length * 0.5);
  if (referenceStart < trailingThreshold && hasTailContent) {
    return content;
  }

  return lines.slice(0, referenceStart).join('\n').trimEnd();
}
