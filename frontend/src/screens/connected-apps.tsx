"use client";

import { useTranslations } from "next-intl";

import { AccountNav } from "@/components/account-nav";
import { ConnectedAppList } from "@/components/connected-app-list";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useMyConnectedApps, useRevokeConnectedApp } from "@/lib/security";

/** The applications one let sign in as oneself with OAuth, and revoking them (7.6). */
export function ConnectedAppsScreen() {
  const t = useTranslations("connectedApps");
  const notify = useNotify();
  const apps = useMyConnectedApps();
  const revoke = useRevokeConnectedApp();
  return (
    <div className="mx-auto max-w-5xl">
      <AccountNav />
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel>
        {apps.isError ? (
          <ErrorState error={apps.error} onRetry={() => void apps.refetch()} className="m-4" />
        ) : !apps.data ? (
          <LoadingState />
        ) : (
          <ConnectedAppList
            caption={t("listTitle")}
            apps={apps.data.items}
            empty={t("none")}
            onRevoke={async (app) => {
              await revoke.mutateAsync(app.id);
              notify(t("revoked", { name: app.client }));
            }}
          />
        )}
      </Panel>
    </div>
  );
}
