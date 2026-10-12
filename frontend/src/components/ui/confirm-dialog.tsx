"use client";

import { AlertDialog } from "radix-ui";
import { useTranslations } from "next-intl";
import { useRef, type ReactNode } from "react";

import { Button } from "./button";

export type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What is about to happen, as a question or a statement: "Delete app-1.0.jar?" */
  title: string;
  /** What it means: what is lost, and that it cannot be undone. */
  children: ReactNode;
  /** The word on the button that does it: "Delete". */
  confirmLabel: string;
  onConfirm: () => void;
  /** The action is under way: the dialog stays, and its button says so. */
  busy?: boolean;
};

/**
 * Asks before something is destroyed (UI-5). Focus starts on Cancel, so that Enter
 * pressed by habit destroys nothing, and Escape closes it.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  onConfirm,
  busy = false,
}: ConfirmDialogProps) {
  const t = useTranslations("confirm");
  // What had the keyboard when the dialog opened. Radix gives focus back to a trigger
  // of its own, and this dialog is opened by whatever its screen chooses.
  const opener = useRef<HTMLElement | null>(null);
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-page/80" />
        <AlertDialog.Content
          onOpenAutoFocus={() => {
            opener.current =
              document.activeElement instanceof HTMLElement ? document.activeElement : null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            opener.current?.focus();
          }}
          className="bevel fixed top-1/2 left-1/2 z-50 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 border border-bad bg-panel p-6"
        >
          <AlertDialog.Title className="text-lg font-semibold text-fg uppercase">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description asChild>
            <div className="mt-2 text-fg-muted">{children}</div>
          </AlertDialog.Description>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <Button>{t("cancel")}</Button>
            </AlertDialog.Cancel>
            <Button
              variant="danger"
              busy={busy}
              onClick={(event) => {
                event.preventDefault();
                onConfirm();
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
