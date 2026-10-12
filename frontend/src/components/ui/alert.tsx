import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type Tone = "info" | "success" | "warning" | "danger";

// A tone is never colour alone (UI-15): each has its own icon, and the text says the rest.
const TONES: Record<Tone, { icon: LucideIcon; border: string; ink: string }> = {
  info: { icon: Info, border: "border-neon-cyan", ink: "text-ink-cyan" },
  success: { icon: CircleCheck, border: "border-ok", ink: "text-ink-ok" },
  warning: { icon: TriangleAlert, border: "border-warn", ink: "text-ink-warn" },
  danger: { icon: CircleAlert, border: "border-bad", ink: "text-ink-bad" },
};

export type AlertProps = {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  className?: string;
};

/**
 * Something the person should know now. A failure or a warning interrupts a screen
 * reader; anything else waits its turn.
 */
export function Alert({ tone = "info", title, children, className }: AlertProps) {
  const { icon: Icon, border, ink } = TONES[tone];
  const urgent = tone === "danger" || tone === "warning";
  return (
    <div
      role={urgent ? "alert" : "status"}
      className={cn("flex gap-3 rounded-sm border-l-4 bg-raised px-4 py-3", border, className)}
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-5 shrink-0", ink)} />
      <div className="min-w-0 text-fg">
        {title ? <p className={cn("font-semibold", ink)}>{title}</p> : null}
        {children ? <div className="text-sm break-words">{children}</div> : null}
      </div>
    </div>
  );
}

/** A state in a word, with its icon: "Online", "Offline". */
export function StatusTag({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  const { icon: Icon, border, ink } = TONES[tone];
  return (
    <span
      className={cn(
        "label-caps inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5",
        border,
        ink,
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}
