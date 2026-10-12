"use client";

import { Inbox, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { isApiError } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { useErrorText } from "@/lib/errors";

import { Alert } from "./alert";
import { Button } from "./button";
import { Spinner } from "./spinner";

/** The three states every screen has besides its content (UI-5). */

/** Something is being fetched and there is nothing to draw yet. */
export function LoadingState({ className }: { className?: string }) {
  const t = useTranslations("app");
  return (
    <div
      role="status"
      className={cn("flex items-center justify-center gap-3 p-10 text-fg-muted", className)}
    >
      <Spinner className="size-5 text-ink-cyan" />
      <span>{t("loading")}</span>
    </div>
  );
}

/** A grey shape where content will be. Rows of them stand for a list that is on its way. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("h-4 rounded-sm bg-raised motion-safe:animate-pulse", className)}
    />
  );
}

/** There is nothing to show, which is not a failure: say so, and what could be done. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 p-10 text-center">
      <Inbox aria-hidden="true" className="size-10 text-neon-magenta" />
      <h2 className="text-lg font-semibold text-fg uppercase">{title}</h2>
      {children ? <p className="max-w-prose text-fg-muted">{children}</p> : null}
      {action}
    </div>
  );
}

/**
 * A request failed. What is said: what went wrong, the API's code for it, and which
 * request it was, so that whoever reports it can name it.
 */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const t = useTranslations("states");
  const say = useErrorText();
  const api = isApiError(error) ? error : null;
  return (
    <Alert tone="danger" title={t("errorTitle")} className={className}>
      <p>{say(error)}</p>
      {api ? (
        <p className="mt-1 font-mono text-xs text-fg-muted">
          <span>{t("code", { code: api.code })}</span>
          {api.requestId ? (
            <span className="ml-3">{t("requestId", { id: api.requestId })}</span>
          ) : null}
        </p>
      ) : null}
      {onRetry ? (
        <Button size="sm" className="mt-3" onClick={onRetry}>
          <RotateCw aria-hidden="true" className="size-4" />
          {t("tryAgain")}
        </Button>
      ) : null}
    </Alert>
  );
}
