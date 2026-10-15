"use client";

import { Download, File, Folder, Search, Trash2, Upload, Wrench, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type RefObject } from "react";

import { Alert } from "@/components/ui/alert";
import { Breadcrumbs, type Crumb } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Snippet, Time } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { Entry, RepositoryView } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import {
  deleteFolder,
  forget,
  may,
  takesUploads,
  useAsset,
  useDeleteAsset,
  useFolder,
  useRepository,
  type FolderProgress,
} from "@/lib/content";
import { formatBytes } from "@/lib/format";
import { movedTo } from "@/lib/places";
import {
  browseHref,
  componentHref,
  httpAddress,
  parentOf,
  parseBrowse,
  repositorySettingsHref,
  searchHref,
  split,
  uploadHref,
} from "@/lib/paths";
import { allows } from "@/lib/session/rules";
import { askAgainIfChanged, useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

const TYPES = ["hosted", "proxy", "group"] as const;

function useTypeName(): (type: string) => string {
  const t = useTranslations("home");
  return (type) =>
    (TYPES as readonly string[]).includes(type) ? t(`types.${type as "hosted"}`) : type;
}

/** A group holds nothing of its own: what it shows is who is behind it. */
function Members({ repository }: { repository: RepositoryView }) {
  const t = useTranslations("browse");
  const members = repository.members ?? [];
  return (
    <Panel className="p-6">
      <h2 className="mb-2 text-lg font-semibold text-fg uppercase">{t("membersTitle")}</h2>
      <p className="mb-4 text-fg-muted">{t("membersIntro")}</p>
      {members.length === 0 ? (
        <p className="text-fg-muted">{t("noMembers")}</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {members.map((member) => (
            <li key={member}>
              <AppLink
                href={browseHref(member)}
                className="font-mono text-ink-cyan underline-offset-4 hover:underline"
              >
                {member}
              </AppLink>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

function Entries({
  repository,
  folder,
  entries,
  chosen,
}: {
  repository: string;
  folder: string;
  entries: Entry[];
  chosen: string | null;
}) {
  const t = useTranslations("browse");
  return (
    <Table caption={t("entriesOf", { folder: folder || repository })}>
      <thead>
        <tr>
          <Th>{t("columns.name")}</Th>
          <Th className="text-right">{t("columns.size")}</Th>
          <Th>{t("columns.modified")}</Th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const isFolder = entry.kind === "folder";
          const current = !isFolder && entry.name === chosen;
          const Icon = isFolder ? Folder : File;
          return (
            // A name can be a file and a folder at once: the kind tells the two apart.
            <tr
              key={`${entry.kind}:${entry.name}`}
              className={cn("hover:bg-raised", current && "bg-raised")}
            >
              <Td>
                <AppLink
                  href={
                    isFolder
                      ? browseHref(repository, entry.path)
                      : browseHref(repository, folder, entry.name)
                  }
                  aria-label={t(isFolder ? "folderNamed" : "fileNamed", { name: entry.name })}
                  data-file={isFolder ? undefined : entry.name}
                  aria-current={current ? "true" : undefined}
                  scroll={false}
                  className={cn(
                    "flex items-center gap-2 rounded-sm font-mono break-all underline-offset-4 hover:underline",
                    current ? "text-ink-cyan" : "text-fg",
                  )}
                >
                  <Icon
                    aria-hidden="true"
                    className={cn("size-4 shrink-0", isFolder ? "text-neon-acid" : "text-fg-muted")}
                  />
                  {entry.name}
                </AppLink>
              </Td>
              <Td className="text-right font-mono whitespace-nowrap text-fg-muted">
                {entry.size === null || entry.size === undefined ? "" : formatBytes(entry.size)}
              </Td>
              <Td className="whitespace-nowrap text-fg-muted">
                {entry.modified ? <Time value={entry.modified} /> : null}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

/** Everything the API says of one file, and what can be done with it. */
function FileDetails({
  repository,
  folder,
  name,
}: {
  repository: RepositoryView;
  folder: string;
  name: string;
}) {
  const t = useTranslations("browse");
  const router = useRouter();
  const notify = useNotify();
  const session = useSession();
  const path = folder ? `${folder}/${name}` : name;
  const remove = useDeleteAsset(repository.name);
  // Once it is deleted it is not asked for again: the answer would be an error, shown
  // here for the moment before the screen returns to the folder.
  const asset = useAsset(repository.name, remove.isSuccess ? null : path);
  const [asking, setAsking] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  // Whoever chose the file by keyboard is taken to what they asked for.
  useEffect(() => heading.current?.focus(), [path]);

  const close = browseHref(repository.name, folder);
  const file = asset.data;
  const download = httpAddress(file?.download);
  return (
    <Panel role="region" aria-label={t("detailsOf", { name })} className="p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <h2
          ref={heading}
          tabIndex={-1}
          className="min-w-0 font-mono text-base font-semibold break-all text-fg outline-none"
        >
          {name}
        </h2>
        <AppLink
          href={close}
          scroll={false}
          aria-label={t("closeDetails")}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-fg-muted hover:text-fg"
        >
          <X aria-hidden="true" className="size-4" />
        </AppLink>
      </div>
      {asset.isError ? (
        <ErrorState error={asset.error} onRetry={() => void asset.refetch()} />
      ) : !file ? (
        <LoadingState className="p-4" />
      ) : (
        <>
          <Facts>
            <Fact name={t("facts.path")} copy={file.path} mono>
              {file.path}
            </Fact>
            <Fact name={t("facts.size")}>{formatBytes(file.size)}</Fact>
            <Fact name={t("facts.type")}>{file.content_type}</Fact>
            <Fact name={t("facts.sha256")} copy={file.sha256} mono>
              {file.sha256}
            </Fact>
            <Fact name={t("facts.sha1")} copy={file.sha1} mono>
              {file.sha1}
            </Fact>
            <Fact name={t("facts.md5")} copy={file.md5} mono>
              {file.md5}
            </Fact>
            <Fact name={t("facts.sha512")} copy={file.sha512} mono>
              {file.sha512}
            </Fact>
            <Fact name={t("facts.blobStore")}>{file.blob_store}</Fact>
            <Fact name={t("facts.storedBy")}>{file.created_by}</Fact>
            <Fact name={t("facts.created")}>
              <Time value={file.created} />
            </Fact>
            <Fact name={t("facts.modified")}>
              <Time value={file.modified} />
            </Fact>
            <Fact name={t("facts.lastDownloaded")}>
              <Time value={file.last_downloaded} />
            </Fact>
            {file.component ? (
              <Fact name={t("facts.component")}>
                <AppLink
                  href={componentHref(repository.name, file.component.id)}
                  className="text-ink-cyan underline-offset-4 hover:underline"
                >
                  {[file.component.namespace, file.component.name, file.component.version]
                    .filter(Boolean)
                    .join(" : ")}
                </AppLink>
              </Fact>
            ) : null}
          </Facts>
          <div className="mt-5 flex flex-wrap gap-2">
            {download ? (
              <Button asChild variant="primary" size="sm">
                <a href={download}>
                  <Download aria-hidden="true" className="size-4" />
                  {t("download")}
                </a>
              </Button>
            ) : null}
            {may(session.data, repository, "delete") ? (
              <Button size="sm" onClick={() => setAsking(true)}>
                <Trash2 aria-hidden="true" className="size-4" />
                {t("delete")}
              </Button>
            ) : null}
          </div>
          {remove.isError ? <ErrorState error={remove.error} className="mt-4" /> : null}
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title={t("deleteFileTitle", { name })}
            confirmLabel={t("delete")}
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(file.path, {
                onSuccess: () => {
                  notify(t("deleted", { name }));
                  router.replace(close, { scroll: false });
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {t("deleteFileBody")}
          </ConfirmDialog>
        </>
      )}
    </Panel>
  );
}

/** Deleting everything under a folder: asked for by name, done in pieces, and stoppable. */
function DeleteFolder({ repository, folder }: { repository: string; folder: string }) {
  const t = useTranslations("browse");
  const router = useRouter();
  const notify = useNotify();
  const client = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [progress, setProgress] = useState<FolderProgress | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const stop = useRef<AbortController | null>(null);
  const name = split(folder).name;

  async function run() {
    stop.current = new AbortController();
    setFailure(null);
    setProgress({ deleted: 0, skipped: 0 });
    try {
      const done = await deleteFolder(repository, folder, {
        onProgress: setProgress,
        signal: stop.current.signal,
      });
      await forget(client, repository);
      setAsking(false);
      notify(
        done.finished
          ? t("folderDeleted", { name, deleted: done.deleted, skipped: done.skipped })
          : t("folderStopped", { name, deleted: done.deleted }),
      );
      if (done.finished && done.skipped === 0) {
        router.replace(browseHref(repository, parentOf(folder) ?? ""));
      }
    } catch (error) {
      // Not a request of the store's: its rule for a session that changed is applied here.
      askAgainIfChanged(client, error);
      await forget(client, repository);
      setFailure(error);
    } finally {
      setProgress(null);
    }
  }

  return (
    <>
      <Button
        size="sm"
        onClick={() => {
          setFailure(null); // what went wrong before is not said of a try not yet made
          setAsking(true);
        }}
      >
        <Trash2 aria-hidden="true" className="size-4" />
        {t("deleteFolder")}
      </Button>
      <ConfirmDialog
        open={asking}
        onOpenChange={(open) => {
          if (!open) stop.current?.abort(); // closing it stops after the piece under way
          setAsking(open);
        }}
        title={t("deleteFolderTitle", { name })}
        confirmLabel={t("deleteFolder")}
        mustType={name}
        busy={progress !== null}
        onConfirm={() => void run()}
      >
        <p>{t("deleteFolderBody", { folder })}</p>
        {progress ? (
          <p role="status" className="mt-3 text-fg">
            {t("deletedSoFar", { deleted: progress.deleted })}
          </p>
        ) : null}
        {failure ? <ErrorState error={failure} className="mt-3" /> : null}
      </ConfirmDialog>
    </>
  );
}

function FolderView({
  repository,
  folder,
  file,
  here,
}: {
  repository: RepositoryView;
  folder: string;
  file: string | null;
  /** The present place in the path: where the keyboard goes when nothing nearer is left. */
  here: RefObject<HTMLAnchorElement | null>;
}) {
  const t = useTranslations("browse");
  const session = useSession();
  const listing = useFolder(repository.name, folder);
  const entries = listing.data?.pages.flatMap((page) => page.items) ?? [];
  const uploads = takesUploads(session.data, repository);
  const missing = isApiError(listing.error) && listing.error.status === 404;
  const list = useRef<HTMLDivElement>(null);
  const links = () => Array.from(list.current?.querySelectorAll<HTMLElement>("tbody a") ?? []);

  // When a file's details go (closed, or the file deleted), what had the keyboard goes
  // with them. It is given to the file's entry, or to the folder if the file is gone.
  const shown = useRef(file);
  useEffect(() => {
    const was = shown.current;
    shown.current = file;
    if (file !== null || was === null) return;
    const entry = links().find((link) => link.dataset.file === was);
    (entry ?? here.current)?.focus();
  }, [file, here]);

  // "Show more" may bring the last piece and go: the keyboard is put at the first entry
  // it brought, which is also where reading goes on.
  const more = useRef<number | null>(null);
  useEffect(() => {
    if (more.current === null || entries.length <= more.current) return;
    links()[more.current]?.focus();
    more.current = null;
  }, [entries.length]);

  return (
    <div
      className={cn(
        "grid items-start gap-6",
        file !== null && "lg:grid-cols-[minmax(0,1fr)_26rem]",
      )}
    >
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap gap-2">
          {uploads ? (
            <Button asChild size="sm">
              <AppLink href={uploadHref(repository.name, folder || undefined)}>
                <Upload aria-hidden="true" className="size-4" />
                {t("uploadHere")}
              </AppLink>
            </Button>
          ) : null}
          {folder !== "" && may(session.data, repository, "delete") && !missing ? (
            <DeleteFolder repository={repository.name} folder={folder} />
          ) : null}
        </div>
        {listing.isError ? (
          missing ? (
            <Panel>
              {/* Deleting the last file of a folder ends here: the folder went with it. */}
              <EmptyState
                title={t("noFolderTitle")}
                action={
                  <Button asChild>
                    <AppLink href={browseHref(repository.name)}>
                      {t("toTop", { repository: repository.name })}
                    </AppLink>
                  </Button>
                }
              >
                {t("noFolder", { folder })}
              </EmptyState>
            </Panel>
          ) : (
            <ErrorState error={listing.error} onRetry={() => void listing.refetch()} />
          )
        ) : listing.isPending ? (
          <Panel>
            <LoadingState />
          </Panel>
        ) : entries.length === 0 ? (
          <Panel>
            <EmptyState
              title={t("emptyTitle")}
              action={
                uploads ? (
                  <Button asChild variant="primary">
                    <AppLink href={uploadHref(repository.name)}>{t("uploadHere")}</AppLink>
                  </Button>
                ) : undefined
              }
            >
              {repository.type === "proxy" ? t("emptyProxy") : t("empty")}
            </EmptyState>
          </Panel>
        ) : (
          <Panel>
            <div ref={list}>
              <Entries
                repository={repository.name}
                folder={folder}
                entries={entries}
                chosen={file}
              />
            </div>
            {listing.hasNextPage ? (
              <div className="p-3">
                <Button
                  size="sm"
                  busy={listing.isFetchingNextPage}
                  onClick={() => {
                    more.current = entries.length;
                    void listing.fetchNextPage();
                  }}
                >
                  {t("showMore")}
                </Button>
              </div>
            ) : null}
          </Panel>
        )}
      </div>
      {/* Keyed by the file: what was asked, or went wrong, of one file is not the next one's. */}
      {file !== null ? (
        <FileDetails key={file} repository={repository} folder={folder} name={file} />
      ) : null}
    </div>
  );
}

/**
 * A repository, one folder at a time: the way there as breadcrumbs, the folder's
 * entries, and beside them the details of a file that was chosen.
 */
/**
 * How a machine is set up to use the repository, ready to copy (5.2, 6.2, 7.2): its key,
 * its address and the account it signs in with. Nothing for a format whose clients are
 * given the address alone.
 */
function Setup({ repository }: { repository: RepositoryView }) {
  const t = useTranslations("browse");
  const setup = repository.setup ?? [];
  if (setup.length === 0) return null;
  return (
    <Panel className="mt-6 p-4">
      <h2 className="mb-2 text-lg font-semibold text-fg uppercase">{t("setupTitle")}</h2>
      <p className="mb-4 text-fg-muted">{t("setupIntro")}</p>
      <div className="flex flex-col gap-3">
        {setup.map((snippet) => (
          <Snippet key={snippet.label} label={snippet.label} text={snippet.text} />
        ))}
      </div>
    </Panel>
  );
}

export function BrowseScreen() {
  const t = useTranslations("browse");
  const typeName = useTypeName();
  const where = parseBrowse(usePathname());
  const file = useSearchParams().get("file");
  const session = useSession();
  const repository = useRepository(where?.repository ?? "");

  // Entering a folder replaces the list the link that was followed was in, and what had
  // the keyboard is gone. It is given to the present place in the path, which a screen
  // reader then reads: the folder's name. Not on arrival: a page starts at its top. Nor
  // when a file is chosen in the folder: its details take the keyboard themselves.
  const here = useRef<HTMLAnchorElement>(null);
  const place = where === null ? null : `${where.repository}/${where.folder}`;
  const ready = repository.data !== undefined;
  useEffect(() => {
    if (!ready || place === null) return;
    if (movedTo("browse", place) && file === null) here.current?.focus();
  }, [place, ready, file]);

  if (where === null) return <NothingHere />;
  if (repository.isError) {
    return <ErrorState error={repository.error} onRetry={() => void repository.refetch()} />;
  }
  if (!repository.data) return <LoadingState />;

  const found = repository.data;
  const crumbs: Crumb[] = [{ name: found.name, href: browseHref(found.name) }];
  where.folder.split("/").forEach((segment, index, all) => {
    if (segment)
      crumbs.push({
        name: segment,
        href: browseHref(found.name, all.slice(0, index + 1).join("/")),
      });
  });

  return (
    <>
      <PageHeader
        named
        title={found.name}
        intro={t(found.type === "proxy" ? "kindProxy" : "kind", {
          format: found.format,
          type: typeName(found.type),
        })}
      >
        {session.data !== undefined && allows(session.data, "admin:repositories:read") ? (
          <Button asChild size="sm" variant="ghost">
            <AppLink href={repositorySettingsHref(found.name)}>
              <Wrench aria-hidden="true" className="size-4" />
              {t("settings")}
            </AppLink>
          </Button>
        ) : null}
        {/* Not for a group: search looks in what holds components, and a group holds none. */}
        {found.type === "group" ? null : (
          <Button asChild size="sm" variant="ghost">
            <AppLink href={searchHref({ repository: found.name })}>
              <Search aria-hidden="true" className="size-4" />
              {t("searchIn")}
            </AppLink>
          </Button>
        )}
      </PageHeader>
      {found.online ? null : (
        <Alert tone="warning" className="mb-4">
          {t("offline")}
        </Alert>
      )}
      <Breadcrumbs label={t("path")} crumbs={crumbs} current={here} />
      {found.type === "group" ? (
        <Members repository={found} />
      ) : (
        <FolderView repository={found} folder={where.folder} file={file} here={here} />
      )}
      <Setup repository={found} />
    </>
  );
}
