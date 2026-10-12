"use client";

import { CircleCheck, X } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Notice = { id: number; text: string };

const NotifyContext = createContext<((text: string) => void) | null>(null);

// Long enough to read a sentence, and to reach it with a screen reader.
const STAYS_FOR = 6000;

/**
 * Says that something was done: "Deleted app-1.0.jar". After a delete, the thing that
 * was acted on is gone, so there is nowhere beside it to say so. A notice is read out
 * by a screen reader and goes by itself. What failed is not said here: a failure stays
 * on its screen until it is dealt with.
 */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const t = useTranslations("notifications");
  const [notices, setNotices] = useState<Notice[]>([]);
  const next = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setNotices((shown) => shown.filter((notice) => notice.id !== id));
  }, []);

  const notify = useCallback(
    (text: string) => {
      const id = next.current++;
      setNotices((shown) => [...shown, { id, text }]);
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), STAYS_FOR),
      );
    },
    [dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const region = useMemo(
    () => (
      // Always in the page, so that what appears in it is announced. A region of its
      // own, with a name: a screen reader can go to it, and it is not mistaken for
      // the status of whatever screen is under it.
      <div
        role="region"
        aria-live="polite"
        aria-label={t("label")}
        className="fixed right-4 bottom-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {notices.map((notice) => (
          <div
            key={notice.id}
            className="bevel flex items-start gap-3 border border-ok bg-panel px-4 py-3 shadow-glow-sm"
          >
            <CircleCheck aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-ink-ok" />
            <p className="min-w-0 flex-1 text-sm break-words text-fg">{notice.text}</p>
            <button
              type="button"
              aria-label={t("dismiss")}
              onClick={() => dismiss(notice.id)}
              className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-fg-muted hover:text-fg"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          </div>
        ))}
      </div>
    ),
    [notices, dismiss, t],
  );

  return (
    <NotifyContext.Provider value={notify}>
      {children}
      {region}
    </NotifyContext.Provider>
  );
}

/** A function that says, for a few seconds, that something was done. */
export function useNotify(): (text: string) => void {
  const notify = useContext(NotifyContext);
  if (notify === null) throw new Error("useNotify is used outside NotificationsProvider");
  return notify;
}
