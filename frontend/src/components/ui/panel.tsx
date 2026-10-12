import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A surface that holds one thing: a form, a table, a state. */
export function Panel({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("bevel border border-line bg-panel", className)} {...rest}>
      {children}
    </div>
  );
}

/** The heading of a screen, with what it is for, and its actions at the end. */
export function PageHeader({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-wide text-fg uppercase">{title}</h1>
        {intro ? <p className="mt-1 text-fg-muted">{intro}</p> : null}
      </div>
      {children ? <div className="flex flex-wrap gap-2">{children}</div> : null}
    </header>
  );
}
