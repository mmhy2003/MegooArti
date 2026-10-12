"use client";

import { Check, Copy, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

type Outcome = "idle" | "copied" | "failed";

/** Copies a piece of text: an address, a checksum, a snippet. It says whether it did. */
export function CopyButton({
  text,
  what,
  className,
}: {
  text: string;
  /** What is copied, for the button's name: "the address of maven-releases". */
  what: string;
  className?: string;
}) {
  const t = useTranslations("copy");
  const [outcome, setOutcome] = useState<Outcome>("idle");

  useEffect(() => {
    if (outcome === "idle") return;
    const timer = window.setTimeout(() => setOutcome("idle"), 2000);
    return () => window.clearTimeout(timer);
  }, [outcome]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setOutcome("copied");
    } catch {
      // No permission, or a page that is not served securely.
      setOutcome("failed");
    }
  }

  const Icon = outcome === "copied" ? Check : outcome === "failed" ? X : Copy;
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={t("label", { what })}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-sm border border-transparent",
        "text-fg-muted hover:border-neon-cyan hover:text-ink-cyan",
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-4" />
      <span role="status" className="sr-only">
        {outcome === "copied" ? t("copied") : outcome === "failed" ? t("failed") : ""}
      </span>
    </button>
  );
}
