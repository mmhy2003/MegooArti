"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { AT_ONCE, useManagedRepositories } from "@/lib/administration";
import type { RepositoryOut } from "@/lib/api/types";
import { usePageFocus, useWithinPages } from "@/lib/focus";
import {
  isAddressable,
  MANAGE_REPOSITORIES,
  NEW_REPOSITORY,
  pageHref,
  pageOf,
  repositorySettingsHref,
} from "@/lib/paths";
import { TYPES, type RepositoryType } from "@/lib/repository-form";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

/** Whether a repository answers, in a word or two, each with its own mark. */
function State({ repository, now }: { repository: RepositoryOut; now: number }) {
  const t = useTranslations("manage");
  const until = repository.status?.auto_blocked_until ?? null;
  return (
    <div className="flex flex-wrap gap-1.5">
      <StatusTag tone={repository.online ? "success" : "warning"}>
        {repository.online ? t("online") : t("offline")}
      </StatusTag>
      {repository.status?.blocked ? (
        <StatusTag tone="warning">{t("state.blocked")}</StatusTag>
      ) : until !== null && new Date(until).getTime() > now ? (
        <StatusTag tone="warning">{t("state.waiting")}</StatusTag>
      ) : null}
    </div>
  );
}

/**
 * Every repository as it is set up (R1): the administrator's list, beside the one for
 * browsing. From here a repository's settings are opened, and a new one is made.
 */
export function ManageRepositoriesScreen() {
  const t = useTranslations("manage");
  const session = useSession();
  const page = pageOf(useSearchParams());
  const repositories = useManagedRepositories(page);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:repositories:write");
  const pages =
    repositories.data === undefined ? undefined : Math.ceil(repositories.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(MANAGE_REPOSITORIES, target);
  const top = usePageFocus<HTMLDivElement>(page, repositories.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);
  // Read once, when the list is shown: whether a proxy is still left alone.
  const [now] = useState(() => Date.now());
  const create = (
    <Button asChild variant="primary" size="sm">
      <AppLink href={NEW_REPOSITORY}>
        <Plus aria-hidden="true" className="size-4" />
        {t("new")}
      </AppLink>
    </Button>
  );

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? create : null}
      </PageHeader>
      {repositories.isError ? (
        <ErrorState error={repositories.error} onRetry={() => void repositories.refetch()} />
      ) : !repositories.data || beyond ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : repositories.data.total === 0 ? (
        <Panel>
          <EmptyState title={t("emptyTitle")} action={mayWrite ? create : undefined}>
            {t("empty")}
          </EmptyState>
        </Panel>
      ) : (
        <Panel>
          {/* Named, and able to take the keyboard: it is put here when a page is turned. */}
          <div
            ref={top}
            tabIndex={-1}
            role="group"
            aria-label={t("title")}
            className="outline-none"
          >
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.name")}</Th>
                  <Th>{t("columns.format")}</Th>
                  <Th>{t("columns.type")}</Th>
                  <Th>{t("columns.state")}</Th>
                  <Th>{t("columns.blobStore")}</Th>
                </tr>
              </thead>
              <tbody>
                {repositories.data.items.map((repository) => (
                  <tr key={repository.name} className="hover:bg-raised">
                    <Td>
                      {isAddressable(repository.name) ? (
                        <AppLink
                          href={repositorySettingsHref(repository.name)}
                          className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                        >
                          {repository.name}
                        </AppLink>
                      ) : (
                        <span className="font-mono font-medium text-fg">{repository.name}</span>
                      )}
                    </Td>
                    <Td>{repository.format}</Td>
                    <Td>
                      {(TYPES as readonly string[]).includes(repository.type)
                        ? t(`types.${repository.type as RepositoryType}`)
                        : repository.type}
                    </Td>
                    <Td>
                      <State repository={repository} now={now} />
                    </Td>
                    <Td className="font-mono text-xs break-all text-fg-muted">
                      {repository.blob_store}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
        </Panel>
      )}
    </>
  );
}
