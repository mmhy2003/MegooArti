"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { StatusTag } from "@/components/ui/alert";
import { CopyButton } from "@/components/ui/copy-button";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { Page, RepositoryView } from "@/lib/api/types";
import { browseHref } from "@/lib/paths";

// As many as one request may ask for. An installation has tens of repositories.
const AT_ONCE = 200;

const TYPES = ["hosted", "proxy", "group"] as const;
type KnownType = (typeof TYPES)[number];

function isKnownType(type: string): type is KnownType {
  return (TYPES as readonly string[]).includes(type);
}

function Rows({ repositories }: { repositories: RepositoryView[] }) {
  const t = useTranslations("home");
  return (
    <tbody>
      {repositories.map((repository) => (
        <tr key={repository.name} className="hover:bg-raised">
          <Td>
            <AppLink
              href={browseHref(repository.name)}
              className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
            >
              {repository.name}
            </AppLink>
          </Td>
          <Td>{repository.format}</Td>
          <Td>{isKnownType(repository.type) ? t(`types.${repository.type}`) : repository.type}</Td>
          <Td>
            {repository.online ? (
              <StatusTag tone="success">{t("online")}</StatusTag>
            ) : (
              <StatusTag tone="warning">{t("offline")}</StatusTag>
            )}
          </Td>
          <Td>
            <span className="flex items-center gap-1">
              <span className="font-mono text-xs break-all text-fg-muted">{repository.url}</span>
              <CopyButton text={repository.url} what={repository.url} />
            </span>
          </Td>
        </tr>
      ))}
    </tbody>
  );
}

function Loading() {
  return (
    <tbody aria-hidden="true">
      {[0, 1, 2].map((row) => (
        <tr key={row}>
          {[0, 1, 2, 3, 4].map((cell) => (
            <Td key={cell}>
              <Skeleton className={cell === 4 ? "w-56" : "w-20"} />
            </Td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

/** The repositories a caller may browse: where browsing starts. */
export function HomeScreen() {
  const t = useTranslations("home");
  const app = useTranslations("app");
  const repositories = useQuery({
    queryKey: ["content", "repositories"],
    queryFn: () => api.get<Page<RepositoryView>>("/content", { query: { limit: AT_ONCE } }),
  });
  const page = repositories.data;

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")} />
      {repositories.isError ? (
        <ErrorState error={repositories.error} onRetry={() => void repositories.refetch()} />
      ) : page && page.items.length === 0 ? (
        <Panel>
          <EmptyState title={t("emptyTitle")}>{t("empty")}</EmptyState>
        </Panel>
      ) : (
        <Panel aria-busy={repositories.isPending || undefined}>
          {repositories.isPending ? (
            <p role="status" className="sr-only">
              {app("loading")}
            </p>
          ) : null}
          <Table caption={t("title")}>
            <thead>
              <tr>
                <Th>{t("columns.name")}</Th>
                <Th>{t("columns.format")}</Th>
                <Th>{t("columns.type")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th>{t("columns.address")}</Th>
              </tr>
            </thead>
            {page ? <Rows repositories={page.items} /> : <Loading />}
          </Table>
          {page && page.total > page.items.length ? (
            <p className="px-4 py-3 text-sm text-fg-muted">
              {t("more", { shown: page.items.length, total: page.total })}
            </p>
          ) : null}
        </Panel>
      )}
    </>
  );
}
