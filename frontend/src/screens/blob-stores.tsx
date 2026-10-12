"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import {
  AT_ONCE,
  useBlobStores,
  useCreateBlobStore,
  useDeleteBlobStore,
} from "@/lib/administration";
import { isApiError } from "@/lib/api/client";
import type { BlobStoreOut } from "@/lib/api/types";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import { formatBytes } from "@/lib/format";
import { BLOB_STORES, isAddressable, pageHref, pageOf } from "@/lib/paths";
import { DEFAULT_BLOB_STORE } from "@/lib/repository-form";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

// The server's rule for a name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

/** What a blob store holds, as columns. Used by the system page as well. */
export function BlobStoreTable({
  caption,
  stores,
  onDelete,
}: {
  caption: string;
  stores: BlobStoreOut[];
  /** Without it, the stores can be seen and not deleted. */
  onDelete?: (store: BlobStoreOut) => void;
}) {
  const t = useTranslations("blobStores");
  return (
    <Table caption={caption}>
      <thead>
        <tr>
          <Th>{t("columns.name")}</Th>
          <Th>{t("columns.directory")}</Th>
          <Th className="text-right">{t("columns.blobs")}</Th>
          <Th className="text-right">{t("columns.size")}</Th>
          <Th className="text-right">{t("columns.available")}</Th>
          {onDelete ? <Th className="text-right">{t("columns.actions")}</Th> : null}
        </tr>
      </thead>
      <tbody>
        {stores.map((store) => (
          <tr key={store.name} className="hover:bg-raised">
            <Td className="font-mono font-medium break-all">{store.name}</Td>
            <Td className="font-mono text-xs break-all text-fg-muted">{store.path}</Td>
            <Td className="text-right font-mono whitespace-nowrap">{store.blob_count}</Td>
            <Td className="text-right font-mono whitespace-nowrap">
              {formatBytes(store.total_bytes)}
            </Td>
            <Td className="text-right font-mono whitespace-nowrap text-fg-muted">
              {store.available_bytes === null ? t("unknown") : formatBytes(store.available_bytes)}
            </Td>
            {onDelete ? (
              <Td className="text-right">
                {store.name === DEFAULT_BLOB_STORE ? (
                  // A repository that names no blob store is put in it: the server keeps it (H7).
                  <span className="text-xs text-fg-subtle">{t("alwaysKept")}</span>
                ) : (
                  <Button
                    size="sm"
                    aria-label={t("deleteNamed", { name: store.name })}
                    onClick={() => onDelete(store)}
                  >
                    {t("delete")}
                  </Button>
                )}
              </Td>
            ) : null}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Create() {
  const t = useTranslations("blobStores");
  const notify = useNotify();
  const create = useCreateBlobStore();
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const { form, tried, attempt, forget } = useAttempts(create.error);
  const refused = refusalsOf(create.error, ["name", "path", "type"]);
  // A name another store has: said at the name.
  const taken =
    isApiError(create.error) && create.error.code === "conflict" ? create.error.message : null;
  // The directory of a store is called as the store is, and . and .. are directories
  // already: the server would speak of one that was never typed (R13).
  const ownName = !NAME.test(name)
    ? t("nameRule")
    : isAddressable(name)
      ? undefined
      : t("nameDots");

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    create.reset();
    if (ownName) return;
    create.mutate(
      // Without a directory, the server gives it one of its own name.
      { name, type: "file", path: path.trim() === "" ? null : path.trim() },
      {
        onSuccess: (made) => {
          notify(t("created", { name: made.name }));
          // Ready for another: empty, and with nothing said to be wrong with it.
          setName("");
          setPath("");
          forget();
        },
      },
    );
  }

  return (
    <Panel className="mb-6 p-6">
      <h2 className={H2}>{t("createTitle")}</h2>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            spellCheck={false}
            autoComplete="off"
            value={name}
            error={tried ? (ownName ?? taken ?? refused.at.name) : undefined}
            onChange={(event) => setName(event.target.value)}
          />
          <TextField
            label={t("fields.directory")}
            hint={t("hints.directory")}
            spellCheck={false}
            autoComplete="off"
            value={path}
            error={tried ? refused.at.path : undefined}
            onChange={(event) => setPath(event.target.value)}
          />
        </div>
        {create.isError && taken === null && refused.elsewhere ? (
          <ErrorState error={create.error} />
        ) : null}
        <div>
          <Button type="submit" variant="primary" busy={create.isPending}>
            <Plus aria-hidden="true" className="size-4" />
            {t("create")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** The blob stores (R10): what each holds, a new one, and deleting one that nothing uses. */
export function BlobStoresScreen() {
  const t = useTranslations("blobStores");
  const session = useSession();
  const notify = useNotify();
  const page = pageOf(useSearchParams());
  const stores = useBlobStores(page);
  const remove = useDeleteBlobStore();
  const mayWrite = session.data !== undefined && allows(session.data, "admin:blobstores:write");
  const pages = stores.data === undefined ? undefined : Math.ceil(stores.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(BLOB_STORES, target);
  const top = usePageFocus<HTMLDivElement>(page, stores.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);
  const [asked, setAsked] = useState<BlobStoreOut | null>(null);
  // The button that was pressed goes with its row: once the dialog is closed, the
  // keyboard is put at the list.
  const deleted = useRef(false);
  useEffect(() => {
    if (asked !== null || !deleted.current) return;
    deleted.current = false;
    top.current?.focus();
  }, [asked, top]);

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title={t("title")} intro={t("intro")} />
      {mayWrite ? <Create /> : null}
      <Panel>
        {stores.isError ? (
          <ErrorState error={stores.error} onRetry={() => void stores.refetch()} className="m-4" />
        ) : !stores.data || beyond ? (
          <LoadingState />
        ) : (
          <>
            <div
              ref={top}
              tabIndex={-1}
              role="group"
              aria-label={t("title")}
              className="outline-none"
            >
              <BlobStoreTable
                caption={t("title")}
                stores={stores.data.items}
                onDelete={
                  mayWrite
                    ? (store) => {
                        remove.reset();
                        setAsked(store);
                      }
                    : undefined
                }
              />
            </div>
            {remove.isError ? <ErrorState error={remove.error} className="m-4" /> : null}
            <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
          </>
        )}
      </Panel>
      <ConfirmDialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
        title={t("deleteAsk", { name: asked?.name ?? "" })}
        confirmLabel={t("deleteStore")}
        mustType={asked?.name}
        busy={remove.isPending}
        onConfirm={() => {
          if (asked === null) return;
          remove.mutate(asked.name, {
            onSuccess: () => {
              notify(t("deleted", { name: asked.name }));
              deleted.current = true;
            },
            onSettled: () => setAsked(null),
          });
        }}
      >
        {t("deleteBody")}
      </ConfirmDialog>
    </div>
  );
}
