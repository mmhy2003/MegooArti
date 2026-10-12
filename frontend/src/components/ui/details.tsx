"use client";

import type { Route } from "next";
import { useTranslations } from "next-intl";
import { useSyncExternalStore, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { exactTime, relativeTime } from "@/lib/format";

import { CopyButton } from "./copy-button";
import { AppLink } from "./link";

/** What is said of one thing: names and their values, a time, a piece of code, pages. */

/** A list of names and values, such as a file's size, type and checksums. */
export function Facts({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm", className)}>
      {children}
    </dl>
  );
}

/** One name and its value. With `copy`, the value can be copied: a checksum, an address. */
export function Fact({
  name,
  copy,
  mono = false,
  children,
}: {
  name: string;
  copy?: string;
  mono?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="label-caps pt-1 text-fg-subtle">{name}</dt>
      <dd className="flex min-w-0 items-start gap-1 text-fg">
        <span className={cn("min-w-0 flex-1 break-all", mono && "font-mono text-xs leading-6")}>
          {children}
        </span>
        {copy ? <CopyButton text={copy} what={name} className="-my-1" /> : null}
      </dd>
    </>
  );
}

// A minute is as fine as "3 minutes ago" gets.
function subscribe(tick: () => void): () => void {
  const timer = window.setInterval(tick, 60_000);
  return () => window.clearInterval(timer);
}
const minute = () => Math.floor(Date.now() / 60_000);

/**
 * A time, as a person reads it and as a log needs it: how long ago, with the exact time
 * in the reader's own zone on hover, and read out in place of the short form.
 */
export function Time({ value }: { value: string | null | undefined }) {
  const t = useTranslations("time");
  const now = useSyncExternalStore(subscribe, minute, () => 0);
  if (!value) return <span className="text-fg-subtle">{t("never")}</span>;
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return <span>{value}</span>;
  const exact = exactTime(moment);
  return (
    <time dateTime={value} title={exact}>
      <span aria-hidden="true">{relativeTime(moment, new Date(now * 60_000))}</span>
      <span className="sr-only">{exact}</span>
    </time>
  );
}

/** Text to copy and paste as it stands: a dependency, a command. */
export function Snippet({ label, text }: { label: string; text: string }) {
  return (
    <figure className="rounded-sm border border-line bg-field">
      <figcaption className="flex items-center justify-between gap-2 border-b border-line px-3 py-1">
        <span className="label-caps text-fg-muted">{label}</span>
        <CopyButton text={text} what={label} />
      </figcaption>
      {/* Reachable by keyboard, since it may scroll sideways. */}
      <pre
        tabIndex={0}
        aria-label={label}
        className="overflow-x-auto p-3 font-mono text-xs leading-5 text-fg"
      >
        {text}
      </pre>
    </figure>
  );
}

/** Numbered pages of a list that has a total: where one is, and the way on and back. */
export function Pager({
  page,
  pages,
  hrefFor,
}: {
  page: number;
  pages: number;
  hrefFor: (page: number) => Route;
}) {
  const t = useTranslations("pager");
  if (pages <= 1) return null;
  const link =
    "label-caps rounded-sm border border-line-strong px-3 py-1.5 text-fg hover:border-neon-cyan";
  const idle = "label-caps rounded-sm border border-line px-3 py-1.5 text-fg-subtle";
  return (
    <nav aria-label={t("label")} className="flex items-center justify-between gap-3 px-4 py-3">
      {page > 1 ? (
        <AppLink href={hrefFor(page - 1)} rel="prev" className={link}>
          {t("previous")}
        </AppLink>
      ) : (
        <span aria-disabled="true" className={idle}>
          {t("previous")}
        </span>
      )}
      <span aria-current="page" className="text-sm text-fg-muted">
        {t("position", { page, pages })}
      </span>
      {page < pages ? (
        <AppLink href={hrefFor(page + 1)} rel="next" className={link}>
          {t("next")}
        </AppLink>
      ) : (
        <span aria-disabled="true" className={idle}>
          {t("next")}
        </span>
      )}
    </nav>
  );
}

/** How much of something is done, as a bar and as words. */
export function Progress({ label, value, max }: { label: string; value: number; max: number }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const shown = new Intl.NumberFormat("en", { style: "percent" }).format(percent / 100);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between gap-3 text-sm text-fg-muted">
        <span>{label}</span>
        <span className="font-mono">{shown}</span>
      </div>
      <progress
        aria-label={label}
        value={value}
        max={max || 1}
        className="h-2 w-full overflow-hidden rounded-sm accent-primary"
      />
    </div>
  );
}
