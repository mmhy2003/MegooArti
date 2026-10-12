import { ChevronRight } from "lucide-react";
import type { Route } from "next";

import { AppLink } from "./link";

export type Crumb = { name: string; href: Route };

/**
 * Where one is, as the way there: each part a link, the last one marked as the present
 * place. `label` names the list for a screen reader.
 */
export function Breadcrumbs({ label, crumbs }: { label: string; crumbs: Crumb[] }) {
  return (
    <nav aria-label={label} className="mb-4">
      <ol className="flex flex-wrap items-center gap-1 font-mono text-sm">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={crumb.href} className="flex min-w-0 items-center gap-1">
              {index > 0 ? (
                <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-fg-subtle" />
              ) : null}
              <AppLink
                href={crumb.href}
                aria-current={last ? "page" : undefined}
                className={
                  last
                    ? "rounded-sm px-1 break-all text-ink-cyan"
                    : "rounded-sm px-1 break-all text-fg-muted underline-offset-4 hover:text-fg hover:underline"
                }
              >
                {crumb.name}
              </AppLink>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
