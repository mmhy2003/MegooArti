"use client";

/**
 * What a person prefers of this UI besides the mode, kept in their browser as the mode
 * is. So far there is one: whether `/` goes to the search box. A shortcut that is one
 * character must be one that can be turned off (WCAG 2.1.4): it gets in the way of
 * whoever dictates, or whose keyboard sends keys they did not mean.
 */
import { useCallback, useSyncExternalStore } from "react";

export const SEARCH_KEY_STORAGE = "megooarti-search-key";
const OFF = "off";
const CHANGED = "megooarti-preferences";

/** Whether `/` goes to the search box. It does unless it was turned off. */
export function searchKeyIsOn(): boolean {
  try {
    return window.localStorage.getItem(SEARCH_KEY_STORAGE) !== OFF;
  } catch {
    return true; // storage cannot be read: as if nothing had been chosen
  }
}

export function setSearchKey(on: boolean): void {
  try {
    if (on) window.localStorage.removeItem(SEARCH_KEY_STORAGE);
    else window.localStorage.setItem(SEARCH_KEY_STORAGE, OFF);
  } catch {
    // Storage is off or full. Nothing can be kept then.
  }
  // The same window is not told of its own writes to storage.
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(changed: () => void): () => void {
  window.addEventListener("storage", changed); // another tab
  window.addEventListener(CHANGED, changed); // this one
  return () => {
    window.removeEventListener("storage", changed);
    window.removeEventListener(CHANGED, changed);
  };
}

/** Whether `/` goes to the search box, and a way to say so. On the server it is on. */
export function useSearchKey(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, searchKeyIsOn, () => true);
  return [on, useCallback((next: boolean) => setSearchKey(next), [])];
}
