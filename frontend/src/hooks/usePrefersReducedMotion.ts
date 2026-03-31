import { useSyncExternalStore } from 'react';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

type StoreListener = () => void;

let mediaQueryList: MediaQueryList | null = null;
let detachMediaQueryListener: (() => void) | null = null;
const storeListeners = new Set<StoreListener>();

function ensureMediaQueryList(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return null;
  }
  if (mediaQueryList) {
    return mediaQueryList;
  }

  mediaQueryList = window.matchMedia(REDUCED_MOTION_QUERY);
  const handleChange = () => {
    storeListeners.forEach((listener) => listener());
  };

  if (mediaQueryList.addEventListener) {
    mediaQueryList.addEventListener('change', handleChange);
    detachMediaQueryListener = () => mediaQueryList?.removeEventListener('change', handleChange);
  } else {
    mediaQueryList.addListener(handleChange);
    detachMediaQueryListener = () => mediaQueryList?.removeListener(handleChange);
  }

  return mediaQueryList;
}

function cleanupMediaQueryList() {
  if (storeListeners.size > 0) {
    return;
  }
  detachMediaQueryListener?.();
  detachMediaQueryListener = null;
  mediaQueryList = null;
}

function subscribe(listener: StoreListener) {
  storeListeners.add(listener);
  ensureMediaQueryList();

  return () => {
    storeListeners.delete(listener);
    cleanupMediaQueryList();
  };
}

function getSnapshot() {
  return ensureMediaQueryList()?.matches ?? false;
}

function getServerSnapshot() {
  return false;
}

export function usePrefersReducedMotion() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
