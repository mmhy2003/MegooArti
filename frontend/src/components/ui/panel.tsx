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
  named = false,
  children,
}: {
  title: string;
  intro?: string;
  /**
   * The title has a name in it that someone chose (a repository, a version). Names
   * tell capitals from small letters, so it is shown as it is written.
   */
  named?: boolean;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1
          className={cn(
            "text-2xl font-semibold text-fg",
            named ? "break-words" : "tracking-wide uppercase",
          )}
        >
          {title}
        </h1>
        {intro ? <p className="mt-1 text-fg-muted">{intro}</p> : null}
      </div>
      {children ? <div className="flex flex-wrap gap-2">{children}</div> : null}
    </header>
  );
}
