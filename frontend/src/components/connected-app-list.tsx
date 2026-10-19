"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Time } from "@/components/ui/details";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import type { ConnectedApp } from "@/lib/api/types";

/**
 * The applications a person let sign in as them with OAuth (MCP spec 7.6): one's own, or
 * a user's as an administrator sees them. An application is known by the name it gave
 * itself, and by where it was sent back to. `onRevoke` returns when it is gone, or throws.
 */
export function ConnectedAppList({
  caption,
  apps,
  onRevoke,
  empty,
}: {
  caption: string;
  apps: ConnectedApp[];
  /** Without it, the applications can be seen and not revoked. */
  onRevoke?: (app: ConnectedApp) => Promise<unknown>;
  empty: string;
}) {
  const t = useTranslations("connectedApps");
  const [asked, setAsked] = useState<ConnectedApp | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const list = useRef<HTMLDivElement>(null);
  // After one is revoked the button that was pressed is gone: the keyboard is put here.
  const revoked = useRef(false);
  useEffect(() => {
    if (asked !== null || !revoked.current) return;
    revoked.current = false;
    list.current?.focus();
  }, [asked]);

  async function revoke(app: ConnectedApp) {
    setBusy(true);
    setFailure(null);
    try {
      await onRevoke?.(app);
      revoked.current = true;
      setAsked(null);
    } catch (error) {
      setAsked(null);
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={list} tabIndex={-1} role="group" aria-label={caption} className="outline-none">
      {apps.length === 0 ? <p className="p-6 text-fg-muted">{empty}</p> : null}
      <Table caption={caption} hidden={apps.length === 0}>
        <thead>
          <tr>
            <Th>{t("columns.app")}</Th>
            <Th>{t("columns.mayDo")}</Th>
            <Th>{t("columns.expires")}</Th>
            <Th>{t("columns.lastUsed")}</Th>
            <Th>{t("columns.connected")}</Th>
            {onRevoke ? <Th className="text-right">{t("columns.actions")}</Th> : null}
          </tr>
        </thead>
        <tbody>
          {apps.map((app) => (
            <tr key={app.id} className="hover:bg-raised">
              <Td>
                <span className="font-medium break-all">{app.client}</span>
                <span className="block text-xs text-fg-muted">
                  {t("sentTo", { host: app.redirect_host })}
                </span>
              </Td>
              <Td>{app.scopes === null ? t("everything") : t("reading")}</Td>
              <Td className="whitespace-nowrap text-fg-muted">
                {app.expires_at === null ? t("never") : <Time value={app.expires_at} />}
              </Td>
              <Td className="whitespace-nowrap text-fg-muted">
                <Time value={app.last_used_at} />
              </Td>
              <Td className="whitespace-nowrap text-fg-muted">
                <Time value={app.created_at} />
              </Td>
              {onRevoke ? (
                <Td className="text-right">
                  <Button
                    size="sm"
                    aria-label={t("revokeNamed", { name: app.client })}
                    onClick={() => setAsked(app)}
                  >
                    {t("revoke")}
                  </Button>
                </Td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
      {failure ? <ErrorState error={failure} className="m-4" /> : null}
      <ConfirmDialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
        title={t("confirmTitle", { name: asked?.client ?? "" })}
        confirmLabel={t("revoke")}
        busy={busy}
        onConfirm={() => {
          if (asked) void revoke(asked);
        }}
      >
        {t("confirmText")}
      </ConfirmDialog>
    </div>
  );
}
