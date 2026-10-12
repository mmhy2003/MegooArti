"use client";

import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager, Time } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { NEW_USER, pageHref, pageOf, userHref, USERS } from "@/lib/paths";
import { AT_ONCE, useUsers } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

/** The users there are (A13): who they are, what roles they hold, and whether they can sign in. */
export function UsersScreen() {
  const t = useTranslations("users");
  const session = useSession();
  const page = pageOf(useSearchParams());
  const users = useUsers(page);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:users:write");

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_USER}>
              <UserPlus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : !users.data ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : (
        <Panel>
          <Table caption={t("title")}>
            <thead>
              <tr>
                <Th>{t("columns.username")}</Th>
                <Th>{t("columns.displayName")}</Th>
                <Th>{t("columns.roles")}</Th>
                <Th>{t("columns.state")}</Th>
                <Th>{t("columns.lastSignIn")}</Th>
              </tr>
            </thead>
            <tbody>
              {users.data.items.map((user) => (
                <tr key={user.id} className="hover:bg-raised">
                  <Td>
                    <AppLink
                      href={userHref(user.id)}
                      className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                    >
                      {user.username}
                    </AppLink>
                  </Td>
                  <Td className="break-words">{user.display_name}</Td>
                  <Td className="font-mono text-xs break-all">{user.roles.join(", ")}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1.5">
                      <StatusTag tone={user.status === "active" ? "success" : "warning"}>
                        {user.status === "active" ? t("active") : t("disabled")}
                      </StatusTag>
                      {user.builtin ? <StatusTag tone="info">{t("builtin")}</StatusTag> : null}
                      {user.must_change_password ? (
                        <StatusTag tone="info">{t("mustChange")}</StatusTag>
                      ) : null}
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap text-fg-muted">
                    <Time value={user.last_login_at} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pager
            page={page}
            pages={Math.ceil(users.data.total / AT_ONCE)}
            hrefFor={(target) => pageHref(USERS, target)}
          />
        </Panel>
      )}
    </>
  );
}
