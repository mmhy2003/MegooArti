import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** A table of rows. It scrolls sideways by itself where the window is narrow (UI-3). */
export function Table({
  className,
  caption,
  children,
  ...rest
}: HTMLAttributes<HTMLTableElement> & { caption: string }) {
  return (
    // `relative`, so that what is hidden from sight inside a cell (it is placed
    // absolutely) scrolls with the table, and does not widen the page.
    <div className="relative overflow-x-auto">
      <table className={cn("w-full border-collapse text-left text-sm", className)} {...rest}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function Th({ className, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        "label-caps border-b border-line-strong px-4 py-3 text-fg-muted whitespace-nowrap",
        className,
      )}
      {...rest}
    />
  );
}

export function Td({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-line px-4 py-3 text-fg", className)} {...rest} />;
}
