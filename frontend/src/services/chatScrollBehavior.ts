interface WheelContainmentInput {
  scrollTop: number;
  clientHeight: number;
  scrollHeight: number;
  deltaY: number;
}

const EDGE_EPSILON = 1;

export function shouldContainWheelScroll({
  scrollTop,
  clientHeight,
  scrollHeight,
  deltaY,
}: WheelContainmentInput): boolean {
  if (!Number.isFinite(deltaY) || deltaY === 0) {
    return false;
  }

  const maxScrollTop = Math.max(0, scrollHeight - clientHeight);
  if (maxScrollTop <= EDGE_EPSILON) {
    return false;
  }

  if (deltaY > 0) {
    return scrollTop < maxScrollTop - EDGE_EPSILON;
  }

  return scrollTop > EDGE_EPSILON;
}
