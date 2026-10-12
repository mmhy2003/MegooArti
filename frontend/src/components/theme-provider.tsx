"use client";

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  applyMode,
  DARK_QUERY,
  resolve,
  STORAGE_KEY,
  storeChoice,
  storedChoice,
  type Mode,
  type ThemeChoice,
} from "@/lib/theme";

type Theme = { choice: ThemeChoice; mode: Mode; choose: (choice: ThemeChoice) => void };

const ThemeContext = createContext<Theme | null>(null);

// The choice lives in the browser's storage, and the system's mode in a media query.
// Both are outside React, so they are read as external stores. The page's head has
// already set the mode by the time any of this runs.
const CHANGED = "megooarti-theme-changed";

function subscribe(notify: () => void): () => void {
  const system = window.matchMedia(DARK_QUERY);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === STORAGE_KEY) notify();
  };
  system.addEventListener("change", notify);
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGED, notify);
  return () => {
    system.removeEventListener("change", notify);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGED, notify);
  };
}

const systemIsDark = () => window.matchMedia(DARK_QUERY).matches;

export function ThemeProvider({ children }: { children: ReactNode }) {
  // On the server nothing is known: "system", and dark, which is what the markup says.
  const choice = useSyncExternalStore<ThemeChoice>(subscribe, storedChoice, () => "system");
  const dark = useSyncExternalStore(subscribe, systemIsDark, () => true);
  const mode = resolve(choice, dark);

  // Before paint, so a change of the system's mode or of the choice never shows late.
  // What is applied is read here, from storage and the system, not taken from `mode`:
  // while the page hydrates, `mode` is still the server's guess, and applying that
  // would undo for a moment what the head's script got right.
  useLayoutEffect(() => applyMode(resolve(storedChoice(), systemIsDark())), [mode]);

  const choose = useCallback((next: ThemeChoice) => {
    storeChoice(next);
    window.dispatchEvent(new Event(CHANGED));
  }, []);

  const theme = useMemo(() => ({ choice, mode, choose }), [choice, mode, choose]);
  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (theme === null) throw new Error("useTheme is used outside ThemeProvider");
  return theme;
}
