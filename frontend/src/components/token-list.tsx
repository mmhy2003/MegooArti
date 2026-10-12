"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Time } from "@/components/ui/details";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import type { TokenInfo } from "@/lib/api/types";

/**
 * API tokens as a table: a person's own, or a user's as an administrator sees them.
 * A token is known by its name and by how its secret begins; the secret itself is
 * never here. `onRevoke` returns when the token is gone, or throws.
 */
export function TokenList({
  caption,
  tokens,
  onRevoke,
  empty,
}: {
  caption: string;
  tokens: TokenInfo[];
  /** Without it, the tokens can be seen and not revoked. */
  onRevoke?: (token: TokenInfo) => Promise<unknown>;
  /** What to say when there is none. */
  empty: string;
}) {
  const t = useTranslations("tokens");
  const [asked, setAsked] = useState<TokenInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const table = useRef<HTMLDivElement>(null);
  // Read once, when the list is first shown: a token that runs out while the page
  // stays open is said to have expired the next time the page is opened.
  const [now] = useState(() => Date.now());

  // The button that was pressed goes with its row, and the dialog gives the keyboard
  // back to that button: once the dialog is closed, the keyboard is put at the list.
  const revoked = useRef(false);
  useEffect(() => {
    if (asked !== null || !revoked.current) return;
    revoked.current = false;
    table.current?.focus();
  }, [asked]);

  async function revoke(token: TokenInfo) {
    setBusy(true);
    setFailure(null);
    try {
      await onRevoke?.(token);
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
    // Named, and able to take the keyboard: after a token is revoked the button that
    // was pressed is gone, and the keyboard is put here, whether or not a token is left.
    <div ref={table} tabIndex={-1} role="group" aria-label={caption} className="outline-none">
      {tokens.length === 0 ? <p className="p-6 text-fg-muted">{empty}</p> : null}
      <Table caption={caption} hidden={tokens.length === 0}>
        <thead>
          <tr>
            <Th>{t("columns.name")}</Th>
            <Th>{t("columns.begins")}</Th>
            <Th>{t("columns.mayDo")}</Th>
            <Th>{t("columns.expires")}</Th>
            <Th>{t("columns.lastUsed")}</Th>
            <Th>{t("columns.created")}</Th>
            {onRevoke ? <Th className="text-right">{t("columns.actions")}</Th> : null}
          </tr>
        </thead>
        <tbody>
          {tokens.map((token) => {
            const expired =
              token.expires_at !== null && new Date(token.expires_at).getTime() <= now;
            return (
              <tr key={token.id} className="hover:bg-raised">
                <Td className="font-medium break-all">{token.name}</Td>
                <Td className="font-mono whitespace-nowrap text-fg-muted">
                  {t("begins", { prefix: token.display_prefix })}
                </Td>
                <Td>
                  {token.scopes === null ? (
                    t("everything")
                  ) : (
                    <ul className="flex flex-col gap-0.5">
                      {token.scopes.map((scope) => (
                        <li key={scope} className="font-mono text-xs break-all">
                          {scope}
                        </li>
                      ))}
                    </ul>
                  )}
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  {token.expires_at === null ? (
                    t("never")
                  ) : expired ? (
                    <StatusTag tone="warning">{t("expired")}</StatusTag>
                  ) : (
                    <Time value={token.expires_at} />
                  )}
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  <Time value={token.last_used_at} />
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  <Time value={token.created_at} />
                </Td>
                {onRevoke ? (
                  <Td className="text-right">
                    <Button
                      size="sm"
                      aria-label={t("revokeNamed", { name: token.name })}
                      onClick={() => setAsked(token)}
                    >
                      {t("revoke")}
                    </Button>
                  </Td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </Table>
      {failure ? <ErrorState error={failure} className="m-4" /> : null}
      <ConfirmDialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
        title={t("revokeTitle", { name: asked?.name ?? "" })}
        confirmLabel={t("revoke")}
        busy={busy}
        onConfirm={() => {
          if (asked) void revoke(asked);
        }}
      >
        {t("revokeBody")}
      </ConfirmDialog>
    </div>
  );
}
