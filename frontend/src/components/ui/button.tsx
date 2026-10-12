import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

import { Spinner } from "./spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

const BASE =
  "bevel label-caps inline-flex items-center justify-center gap-2 border whitespace-nowrap " +
  "transition-[background-color,border-color,box-shadow,color] select-none " +
  "disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "border-primary bg-primary text-on-primary hover:shadow-glow",
  secondary:
    "border-line-strong bg-panel text-fg hover:border-neon-cyan hover:shadow-glow-sm active:bg-raised",
  ghost: "border-transparent bg-transparent text-fg-muted hover:bg-raised hover:text-fg",
  danger: "border-danger bg-danger text-on-danger hover:brightness-110",
};

const SIZES: Record<ButtonSize, string> = {
  md: "min-h-10 px-4 py-2",
  sm: "min-h-8 px-3 py-1",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** The request it started is still going: it cannot be pressed again, and says so. */
  busy?: boolean;
  /** Style the one child as a button, when it is something else: a link. */
  asChild?: boolean;
  children: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  asChild = false,
  className,
  children,
  disabled,
  type,
  ...rest
}: ButtonProps) {
  const classes = cn(BASE, VARIANTS[variant], SIZES[size], className);
  if (asChild) {
    return (
      <Slot.Root className={classes} {...rest}>
        {children}
      </Slot.Root>
    );
  }
  return (
    <button
      type={type ?? "button"}
      className={classes}
      disabled={disabled}
      // Busy, it cannot be pressed, but it keeps the keyboard: a button that is
      // disabled outright drops focus to the page.
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      {...rest}
      onClick={busy ? (event) => event.preventDefault() : rest.onClick}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
}
