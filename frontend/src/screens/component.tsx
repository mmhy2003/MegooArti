"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Snippet, Time } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { may, useComponent, useDeleteComponent, useRepository } from "@/lib/content";
import { formatBytes } from "@/lib/format";
import { browseHref, componentHref, fileHref, parseComponent } from "@/lib/paths";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

/** A package version: what it is, its files, and how to use it from a build or a shell. */
export function ComponentScreen() {
  const t = useTranslations("component");
  const router = useRouter();
  const notify = useNotify();
  const session = useSession();
  const where = parseComponent(usePathname());
  const repository = useRepository(where?.repository ?? "");
  const component = useComponent(where?.repository ?? "", where?.id ?? null);
  const remove = useDeleteComponent(where?.repository ?? "");
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  const failed = repository.isError ? repository : component.isError ? component : null;
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  if (!repository.data || !component.data) return <LoadingState />;

  const found = component.data;
  const title = found.version ? `${found.name} ${found.version}` : found.name;
  return (
    <>
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: where.repository, href: browseHref(where.repository) },
          { name: title, href: componentHref(where.repository, found.id) },
        ]}
      />
      <PageHeader named title={title}>
        {may(session.data, repository.data, "delete") ? (
          <Button size="sm" onClick={() => setAsking(true)}>
            <Trash2 aria-hidden="true" className="size-4" />
            {t("delete")}
          </Button>
        ) : null}
      </PageHeader>
      {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Panel className="p-5">
          <h2 className="mb-3 text-lg font-semibold text-fg uppercase">{t("about")}</h2>
          <Facts>
            <Fact name={t("facts.repository")}>
              <AppLink
                href={browseHref(where.repository)}
                className="font-mono text-ink-cyan underline-offset-4 hover:underline"
              >
                {where.repository}
              </AppLink>
            </Fact>
            <Fact name={t("facts.format")}>{repository.data.format}</Fact>
            {found.namespace ? (
              <Fact name={t("facts.namespace")} copy={found.namespace} mono>
                {found.namespace}
              </Fact>
            ) : null}
            <Fact name={t("facts.name")} copy={found.name} mono>
              {found.name}
            </Fact>
            {found.version ? (
              <Fact name={t("facts.version")} copy={found.version} mono>
                {found.version}
              </Fact>
            ) : null}
            <Fact name={t("facts.created")}>
              <Time value={found.created} />
            </Fact>
            <Fact name={t("facts.modified")}>
              <Time value={found.modified} />
            </Fact>
          </Facts>
        </Panel>
        <Panel className="p-5">
          <h2 className="mb-3 text-lg font-semibold text-fg uppercase">{t("usage")}</h2>
          {found.usage.length === 0 ? (
            <p className="text-fg-muted">{t("noUsage")}</p>
          ) : (
            <div className="flex flex-col gap-3">
              {found.usage.map((snippet) => (
                <Snippet key={snippet.label} label={snippet.label} text={snippet.text} />
              ))}
            </div>
          )}
        </Panel>
      </div>
      <Panel className="mt-6">
        <h2 className="px-4 pt-4 text-lg font-semibold text-fg uppercase">{t("files")}</h2>
        <Table caption={t("files")}>
          <thead>
            <tr>
              <Th>{t("columns.path")}</Th>
              <Th className="text-right">{t("columns.size")}</Th>
              <Th>{t("columns.modified")}</Th>
            </tr>
          </thead>
          <tbody>
            {found.files.map((file) => (
              <tr key={file.path} className="hover:bg-raised">
                <Td>
                  <AppLink
                    href={fileHref(where.repository, file.path)}
                    className="font-mono break-all text-fg underline-offset-4 hover:underline"
                  >
                    {file.path}
                  </AppLink>
                </Td>
                <Td className="text-right font-mono whitespace-nowrap text-fg-muted">
                  {file.size === null || file.size === undefined ? "" : formatBytes(file.size)}
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  {file.modified ? <Time value={file.modified} /> : null}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("deleteTitle", { name: title })}
        confirmLabel={t("delete")}
        busy={remove.isPending}
        onConfirm={() =>
          remove.mutate(found.id, {
            onSuccess: () => {
              notify(t("deleted", { name: title }));
              router.replace(browseHref(where.repository));
            },
            onSettled: () => setAsking(false),
          })
        }
      >
        {t("deleteBody", { count: found.files.length })}
      </ConfirmDialog>
    </>
  );
}
