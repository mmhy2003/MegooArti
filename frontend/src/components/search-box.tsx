"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { cn } from "@/lib/cn";
import { searchHref } from "@/lib/paths";

const KEY = "/";

/** Whether a key press is someone typing into something, and so not a shortcut. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * Search, on every screen: finding a package is what most visitors come for. `/` takes
 * the keyboard here from anywhere that is not itself a place to type.
 */
export function SearchBox({ className }: { className?: string }) {
  const t = useTranslations("searchBox");
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== KEY || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTyping(event.target)) return;
      event.preventDefault();
      input.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    router.push(searchHref({ q: text.trim() }));
  }

  return (
    <form
      role="search"
      aria-label={t("label")}
      onSubmit={submit}
      className={cn("relative", className)}
    >
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle"
      />
      <input
        ref={input}
        type="search"
        name="q"
        aria-label={t("label")}
        aria-keyshortcuts={KEY}
        placeholder={t("placeholder")}
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="min-h-10 w-full rounded-sm border border-line-strong bg-field py-2 pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-neon-cyan focus:shadow-glow-sm"
      />
    </form>
  );
}
