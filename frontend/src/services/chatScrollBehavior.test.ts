import { describe, expect, it } from 'vitest';

import { shouldContainWheelScroll } from './chatScrollBehavior';

describe('chatScrollBehavior', () => {
  it('returns false when the container does not overflow', () => {
    expect(
      shouldContainWheelScroll({
        scrollTop: 0,
        clientHeight: 600,
        scrollHeight: 600,
        deltaY: 120,
      })
    ).toBe(false);
  });

  it('contains wheel scroll when scrolling down before reaching bottom', () => {
    expect(
      shouldContainWheelScroll({
        scrollTop: 200,
        clientHeight: 600,
        scrollHeight: 1200,
        deltaY: 120,
      })
    ).toBe(true);
  });

  it('does not contain wheel scroll when already at bottom and scrolling down', () => {
    expect(
      shouldContainWheelScroll({
        scrollTop: 600,
        clientHeight: 600,
        scrollHeight: 1200,
        deltaY: 120,
      })
    ).toBe(false);
  });

  it('contains wheel scroll when scrolling up before reaching top', () => {
    expect(
      shouldContainWheelScroll({
        scrollTop: 200,
        clientHeight: 600,
        scrollHeight: 1200,
        deltaY: -120,
      })
    ).toBe(true);
  });

  it('does not contain wheel scroll when already at top and scrolling up', () => {
    expect(
      shouldContainWheelScroll({
        scrollTop: 0,
        clientHeight: 600,
        scrollHeight: 1200,
        deltaY: -120,
      })
    ).toBe(false);
  });
});
