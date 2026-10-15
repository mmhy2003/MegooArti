"use client";

import { AlertDialog } from "radix-ui";
import { useTranslations } from "next-intl";
import { useRef, useState, type ReactNode } from "react";

import { Button } from "./button";
import { TextField } from "./field";

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
  /**
   * For what takes much with it (a folder, a repository): this must be typed, exactly,
   * before the button that does it can be pressed.
   */
  mustType?: string;
  /**
   * Where the keyboard goes when the dialog closes, if not back to what opened it: the
   * field a refusal is about. Asked as it closes.
   */
  returnFocus?: () => HTMLElement | null;
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
  mustType,
  returnFocus,
}: ConfirmDialogProps) {
  const t = useTranslations("confirm");
  const [typed, setTyped] = useState("");
  // The next time it opens, the name is typed again: whoever closed it, the dialog or
  // the screen that owns it.
  if (!open && typed !== "") setTyped("");
  const allowed = mustType === undefined || typed === mustType;
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
            (returnFocus?.() ?? opener.current)?.focus();
          }}
          className="bevel fixed top-1/2 left-1/2 z-50 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 border border-bad bg-panel p-6"
        >
          {/* Not in capitals: it names what goes, and a name is shown as it is written. */}
          <AlertDialog.Title className="text-lg font-semibold break-words text-fg">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description asChild>
            <div className="mt-2 text-fg-muted">{children}</div>
          </AlertDialog.Description>
          {mustType !== undefined ? (
            <TextField
              className="mt-4"
              label={t("typeToConfirm", { name: mustType })}
              plainLabel
              autoComplete="off"
              spellCheck={false}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
            />
          ) : null}
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <Button>{t("cancel")}</Button>
            </AlertDialog.Cancel>
            <Button
              variant="danger"
              busy={busy}
              disabled={!allowed}
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
