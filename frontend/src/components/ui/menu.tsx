"use client";

import { Check } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

/**
 * A menu that opens from a button. Radix gives it its behaviour: the arrow keys, Home
 * and End, typing to find an item, Escape, and focus returning to the button.
 */

export const Menu = DropdownMenu.Root;
export const MenuTrigger = DropdownMenu.Trigger;
export const MenuRadioGroup = DropdownMenu.RadioGroup;

const ITEM =
  "flex cursor-default items-center gap-2 rounded-sm px-3 py-2 text-sm text-fg outline-none select-none " +
  "data-[highlighted]:bg-raised data-[highlighted]:text-ink-cyan data-[disabled]:opacity-55";

export function MenuContent({
  className,
  children,
  ...rest
}: ComponentProps<typeof DropdownMenu.Content>) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        sideOffset={8}
        align="end"
        className={cn(
          "bevel z-50 min-w-48 border border-line-strong bg-panel p-1 shadow-glow-sm",
          className,
        )}
        {...rest}
      >
        {children}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  );
}

export function MenuItem({ className, ...rest }: ComponentProps<typeof DropdownMenu.Item>) {
  return <DropdownMenu.Item className={cn(ITEM, className)} {...rest} />;
}

export function MenuLabel({ className, ...rest }: ComponentProps<typeof DropdownMenu.Label>) {
  return (
    <DropdownMenu.Label
      className={cn("label-caps px-3 py-2 text-fg-subtle", className)}
      {...rest}
    />
  );
}

export function MenuSeparator() {
  return <DropdownMenu.Separator className="my-1 h-px bg-line" />;
}

/** One of several choices of which one is in force: it shows a tick when it is. */
export function MenuRadioItem({
  className,
  children,
  ...rest
}: ComponentProps<typeof DropdownMenu.RadioItem>) {
  return (
    <DropdownMenu.RadioItem className={cn(ITEM, "relative pr-8", className)} {...rest}>
      {children}
      <DropdownMenu.ItemIndicator className="absolute right-3">
        <Check aria-hidden="true" className="size-4 text-ink-cyan" />
      </DropdownMenu.ItemIndicator>
    </DropdownMenu.RadioItem>
  );
}
