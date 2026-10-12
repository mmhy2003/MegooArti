"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { PermissionList } from "@/components/permission-rows";
import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import type { RoleOut } from "@/lib/api/types";
import { roleHref, userHref, USERS } from "@/lib/paths";
import { useAnonymousUser, useEveryRole, useSetAnonymousAccess, useSettings } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-3 text-lg font-semibold text-fg uppercase";

/**
 * Every pattern the roles of these names grant, with those of the roles they contain.
 * Only what concerns repositories: whatever its roles say, a request without
 * credentials is allowed nothing else.
 */
function patternsOf(held: string[], roles: RoleOut[]): string[] {
  const byName = new Map(roles.map((role) => [role.name, role]));
  const seen = new Set<string>();
  const patterns = new Set<string>();
  const visit = (name: string) => {
    if (seen.has(name)) return;
    seen.add(name);
    const role = byName.get(name);
    role?.permissions.forEach((pattern) => patterns.add(pattern));
    role?.roles.forEach(visit);
  };
  held.forEach(visit);
  return Array.from(patterns)
    .filter((pattern) => ["*", "repository"].includes(pattern.split(":")[0] ?? ""))
    .sort();
}

/** What a visitor may do, as far as this caller may see it: the anonymous user and its roles. */
function Allowed() {
  const t = useTranslations("anonymous");
  const session = useSession();
  const may = (permission: string) =>
    session.data !== undefined && allows(session.data, permission);
  const readable = may("admin:users:read") && may("admin:roles:read");
  const user = useAnonymousUser(readable);
  const roles = useEveryRole(readable);

  if (!readable) return <p className="text-fg-muted">{t("notReadable")}</p>;
  const failed = user.isError ? user : roles.isError ? roles : null;
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  if (user.data === undefined || !roles.data) return <LoadingState className="p-4" />;
  if (user.data === null) {
    return (
      <p className="flex flex-wrap gap-x-2 text-fg-muted">
        <span>{t("userNotFound")}</span>
        <AppLink href={USERS} className="text-ink-cyan underline-offset-4 hover:underline">
          {t("toUsers")}
        </AppLink>
      </p>
    );
  }
  const held = user.data.roles;
  return (
    <div className="flex flex-col gap-4">
      <p className="flex flex-wrap gap-x-2 text-fg-muted">
        <span>{t("rolesIntro")}</span>
        <AppLink
          href={userHref(user.data.id)}
          className="text-ink-cyan underline-offset-4 hover:underline"
        >
          {t("toUser")}
        </AppLink>
      </p>
      {held.length === 0 ? (
        <p className="text-fg">{t("noRoles")}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {held.map((name) => (
            <li key={name}>
              <AppLink
                href={roleHref(name)}
                className="rounded-sm border border-line-strong px-2 py-1 font-mono text-sm text-ink-cyan hover:border-neon-cyan"
              >
                {name}
              </AppLink>
            </li>
          ))}
        </ul>
      )}
      <PermissionList patterns={patternsOf(held, roles.data.items)} empty={t("grantsNothing")} />
      <p className="text-sm text-fg-subtle">{t("onlyRepositories")}</p>
    </div>
  );
}

/**
 * Whether someone who is not signed in may use the server at all (A9). It is the one
 * setting that makes content public, so turning it on asks first.
 */
export function AnonymousAccessScreen() {
  const t = useTranslations("anonymous");
  const session = useSession();
  const notify = useNotify();
  const settings = useSettings();
  const change = useSetAnonymousAccess();
  const [asking, setAsking] = useState(false);

  if (settings.isError) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  if (!settings.data) return <LoadingState />;

  const on = settings.data.anonymous_access.enabled;
  const mayWrite = session.data !== undefined && allows(session.data, "admin:settings:write");
  const set = (enabled: boolean) =>
    change.mutate(enabled, {
      onSuccess: () => notify(enabled ? t("turnedOn") : t("turnedOff")),
      onSettled: () => setAsking(false),
    });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-fg">{t("state")}</span>
            <StatusTag tone={on ? "warning" : "success"}>{on ? t("on") : t("off")}</StatusTag>
          </div>
          {mayWrite ? (
            <Button
              variant={on ? "primary" : "secondary"}
              busy={change.isPending && !asking}
              onClick={() => (on ? set(false) : setAsking(true))}
            >
              {on ? t("turnOff") : t("turnOn")}
            </Button>
          ) : null}
        </div>
        <p className="mt-3 text-fg-muted">{on ? t("onMeans") : t("offMeans")}</p>
        {change.isError ? <ErrorState error={change.error} className="mt-4" /> : null}
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("allowedTitle")}</h2>
        <Allowed />
      </Panel>
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("ask")}
        confirmLabel={t("turnOn")}
        busy={change.isPending}
        onConfirm={() => set(true)}
      >
        {t("askBody")}
      </ConfirmDialog>
    </div>
  );
}
