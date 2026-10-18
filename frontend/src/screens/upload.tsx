"use client";

import { Plus, Upload as UploadIcon, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, FilePicker } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import type { RepositoryView, Uploaded } from "@/lib/api/types";
import { upload, type Sent } from "@/lib/api/upload";
import { forget, takesUploads, useRepositories, useRepository } from "@/lib/content";
import { formatBytes } from "@/lib/format";
import { browseHref, fileHref, parseUpload, uploadHref } from "@/lib/paths";
import { askAgainIfChanged, useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The formats the form knows: each has its fields, and its texts in the messages.
const UPLOADABLE = ["raw", "maven", "npm", "pypi", "apt", "yum", "apk", "nuget"] as const;
type Uploadable = (typeof UPLOADABLE)[number];
// Those whose files are put in a directory that is chosen. An APT package's place is
// its pool path, which the package says.
const IN_A_DIRECTORY = new Set(["raw", "yum", "apk"]);
// Those that take several files at once, and the files each takes.
const SEVERAL = new Set(["raw", "pypi", "apt", "yum", "apk", "nuget"]);
const ACCEPTED: Partial<Record<string, string>> = {
  npm: ".tgz,.tar.gz",
  pypi: ".whl,.tar.gz,.zip",
  apt: ".deb",
  yum: ".rpm",
  apk: ".apk",
  nuget: ".nupkg,.snupkg",
};

function isUploadable(format: string): format is Uploadable {
  return (UPLOADABLE as readonly string[]).includes(format);
}

/** What the API refused, by the name of the field or the part it refused it at. */
type Refusals = Record<string, string>;

// Refusals of the files themselves, which name no field: a package the server cannot
// take, and, of NuGet, a symbol package whose package is not there yet. Said at the files.
const OF_THE_FILES = new Set(["invalid_package"]);
const OF_NUGETS_FILES = new Set(["invalid_package", "not_found"]);

function refusalsOf(error: unknown, format: string): Refusals {
  const ofTheFiles = format === "nuget" ? OF_NUGETS_FILES : OF_THE_FILES;
  if (isApiError(error) && ofTheFiles.has(error.code) && error.details.length === 0) {
    return { file: error.message };
  }
  if (!isApiError(error) || error.code !== "validation_error") return {};
  return Object.fromEntries(
    error.details.filter((detail) => detail.field).map((detail) => [detail.field, detail.message]),
  );
}

// The fields and parts the form has a place for. What the API refuses elsewhere is
// shown whole.
const PLACED = new Set([
  "directory",
  "group",
  "artifact",
  "version",
  "packaging",
  "tag",
  "summary",
  "requires_python",
  "keywords",
  "file",
  "pom",
]);

/** A form's own state: text fields by the API's names, and files by the part they go in. */
type Extra = { id: number; classifier: string; files: File[] };

/** The form of one format. It gives back the parts to send, or null if something is missing. */
function useUploadForm(repository: RepositoryView, directory: string) {
  const [fields, setFields] = useState<Record<string, string>>({
    directory,
    packaging: "jar",
    tag: "latest",
  });
  const [generatePom, setGeneratePom] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [pom, setPom] = useState<File[]>([]);
  const [extras, setExtras] = useState<Extra[]>([]);
  const nextId = useRef(1);

  const set = (name: string) => (event: { target: { value: string } }) =>
    setFields((was) => ({ ...was, [name]: event.target.value }));

  function body(): FormData {
    const form = new FormData();
    const put = (name: string) => {
      const value = (fields[name] ?? "").trim();
      if (value) form.append(name, value);
    };
    for (const file of files) form.append("file", file, file.name);
    switch (repository.format) {
      case "maven":
        ["group", "artifact", "version", "packaging"].forEach(put);
        form.append("generate_pom", generatePom ? "true" : "false");
        for (const file of pom) form.append("pom", file, file.name);
        for (const extra of extras) {
          for (const file of extra.files)
            form.append(`file.${extra.classifier.trim()}`, file, file.name);
        }
        break;
      case "npm":
        put("tag");
        break;
      case "pypi":
        ["summary", "requires_python", "keywords"].forEach(put);
        break;
      default:
        if (IN_A_DIRECTORY.has(repository.format)) put("directory");
    }
    return form;
  }

  function reset() {
    setFiles([]);
    setPom([]);
    setExtras([]);
  }

  return {
    fields,
    set,
    generatePom,
    setGeneratePom,
    files,
    setFiles,
    pom,
    setPom,
    extras,
    addExtra: () =>
      setExtras((was) => [...was, { id: nextId.current++, classifier: "", files: [] }]),
    changeExtra: (id: number, change: Partial<Extra>) =>
      setExtras((was) => was.map((extra) => (extra.id === id ? { ...extra, ...change } : extra))),
    removeExtra: (id: number) => setExtras((was) => was.filter((extra) => extra.id !== id)),
    body,
    reset,
    size: [...files, ...pom, ...extras.flatMap((extra) => extra.files)].reduce(
      (sum, file) => sum + file.size,
      0,
    ),
    hasFile: files.length > 0 || pom.length > 0 || extras.some((extra) => extra.files.length > 0),
  };
}

function Stored({ repository, stored }: { repository: string; stored: Uploaded }) {
  const t = useTranslations("upload");
  return (
    <Alert tone="success" title={t("stored", { count: stored.files.length })}>
      <ul className="mt-1 flex flex-col gap-1">
        {stored.files.map((file) => (
          <li key={file.path}>
            <AppLink
              href={fileHref(repository, file.path)}
              className="font-mono break-all text-ink-cyan underline-offset-4 hover:underline"
            >
              {file.path}
            </AppLink>
          </li>
        ))}
      </ul>
    </Alert>
  );
}

function UploadForm({ repository, directory }: { repository: RepositoryView; directory: string }) {
  const t = useTranslations("upload");
  const client = useQueryClient();
  const notify = useNotify();
  const form = useUploadForm(repository, directory);
  const [sent, setSent] = useState<Sent | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [stored, setStored] = useState<Uploaded | null>(null);
  const stop = useRef<AbortController | null>(null);
  const fields = useRef<HTMLFormElement>(null);
  const refused = refusalsOf(failure, repository.format);

  // The keyboard goes to the first field that was refused. A screen reader then reads
  // the field and, with it, why: an error that only appears is not heard.
  useEffect(() => {
    fields.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [failure]);
  // A refusal that names a field is shown at the field. Anything else is shown whole.
  const unplaced =
    failure !== null &&
    !Object.keys(refused).some((field) => PLACED.has(field) || field.startsWith("file."));

  async function submit(event: FormEvent) {
    event.preventDefault();
    stop.current = new AbortController();
    setFailure(null);
    setStored(null);
    setSent({ sent: 0, total: form.size });
    try {
      const done = await upload<Uploaded>(
        `/content/${encodeURIComponent(repository.name)}/upload`,
        form.body(),
        { onProgress: setSent, signal: stop.current.signal },
      );
      setStored(done);
      form.reset();
      // Said where a screen reader hears it, and to whoever has gone on to another screen.
      notify(t("storedNotice", { count: done.files.length, repository: repository.name }));
      await forget(client, repository.name);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        notify(t("stopped"));
        // The button that stopped it goes: the keyboard is put at the one that sends.
        fields.current?.querySelector<HTMLElement>('button[type="submit"]')?.focus();
        // Stopped late, the server may have had all of it: what it holds is asked again.
        await forget(client, repository.name);
      } else {
        // Not a request of the store's: its rule for a session that changed is applied here.
        askAgainIfChanged(client, error);
        setFailure(error);
      }
    } finally {
      setSent(null);
    }
  }

  const { fields: texts, set } = form;
  const maven = repository.format === "maven";
  return (
    <form ref={fields} onSubmit={submit} className="flex flex-col gap-5" noValidate>
      {IN_A_DIRECTORY.has(repository.format) ? (
        <TextField
          label={t("fields.directory")}
          hint={
            repository.format === "raw"
              ? t("hints.directory")
              : t(`hints.directoryOf.${repository.format as "yum"}`)
          }
          spellCheck={false}
          value={texts.directory ?? ""}
          error={refused.directory}
          onChange={set("directory")}
        />
      ) : null}
      {maven ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <TextField
              label={t("fields.group")}
              spellCheck={false}
              required
              value={texts.group ?? ""}
              error={refused.group}
              onChange={set("group")}
            />
            <TextField
              label={t("fields.artifact")}
              spellCheck={false}
              required
              value={texts.artifact ?? ""}
              error={refused.artifact}
              onChange={set("artifact")}
            />
            <TextField
              label={t("fields.version")}
              spellCheck={false}
              required
              value={texts.version ?? ""}
              error={refused.version}
              onChange={set("version")}
            />
          </div>
          <TextField
            label={t("fields.packaging")}
            hint={t("hints.packaging")}
            spellCheck={false}
            value={texts.packaging ?? ""}
            error={refused.packaging}
            onChange={set("packaging")}
          />
        </>
      ) : null}
      <FilePicker
        label={
          maven
            ? t("fields.artifactFile")
            : t(repository.format === "npm" ? "fields.tarball" : "fields.files")
        }
        hint={isUploadable(repository.format) ? t(`hints.files.${repository.format}`) : undefined}
        multiple={SEVERAL.has(repository.format)}
        accept={ACCEPTED[repository.format]}
        files={form.files}
        error={refused.file}
        onChange={form.setFiles}
      />
      {maven ? (
        <>
          <FilePicker
            label={t("fields.pom")}
            hint={t("hints.pom")}
            accept=".pom,.xml"
            files={form.pom}
            error={refused.pom}
            onChange={form.setPom}
          />
          <CheckboxField
            label={t("fields.generatePom")}
            hint={t("hints.generatePom")}
            checked={form.generatePom}
            onChange={(event) => form.setGeneratePom(event.target.checked)}
          />
          {form.extras.map((extra) => (
            <fieldset
              key={extra.id}
              className="flex flex-col gap-3 rounded-sm border border-line p-4"
            >
              <legend className="label-caps px-1 text-fg-muted">{t("extraLegend")}</legend>
              <div className="flex items-end gap-3">
                <TextField
                  className="flex-1"
                  label={t("fields.classifier")}
                  hint={t("hints.classifier")}
                  spellCheck={false}
                  value={extra.classifier}
                  error={refused[`file.${extra.classifier.trim()}`]}
                  onChange={(event) =>
                    form.changeExtra(extra.id, { classifier: event.target.value })
                  }
                />
                <Button size="sm" variant="ghost" onClick={() => form.removeExtra(extra.id)}>
                  <X aria-hidden="true" className="size-4" />
                  {t("removeExtra")}
                </Button>
              </div>
              <FilePicker
                label={t("fields.extraFile")}
                files={extra.files}
                onChange={(files) => form.changeExtra(extra.id, { files })}
              />
            </fieldset>
          ))}
          <div>
            <Button size="sm" onClick={form.addExtra}>
              <Plus aria-hidden="true" className="size-4" />
              {t("addExtra")}
            </Button>
          </div>
        </>
      ) : null}
      {repository.format === "npm" ? (
        <TextField
          label={t("fields.tag")}
          hint={t("hints.tag")}
          spellCheck={false}
          value={texts.tag ?? ""}
          error={refused.tag}
          onChange={set("tag")}
        />
      ) : null}
      {repository.format === "pypi" ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <TextField
            label={t("fields.summary")}
            value={texts.summary ?? ""}
            error={refused.summary}
            onChange={set("summary")}
          />
          <TextField
            label={t("fields.requiresPython")}
            hint={t("hints.requiresPython")}
            spellCheck={false}
            value={texts.requires_python ?? ""}
            error={refused.requires_python}
            onChange={set("requires_python")}
          />
          <TextField
            label={t("fields.keywords")}
            value={texts.keywords ?? ""}
            error={refused.keywords}
            onChange={set("keywords")}
          />
        </div>
      ) : null}
      {sent ? (
        <Progress
          label={t("sending", { sent: formatBytes(sent.sent), total: formatBytes(sent.total) })}
          value={sent.sent}
          max={sent.total}
        />
      ) : null}
      {unplaced ? <ErrorState error={failure} /> : null}
      {stored ? <Stored repository={repository.name} stored={stored} /> : null}
      <div className="flex flex-wrap gap-3">
        <Button type="submit" variant="primary" busy={sent !== null} disabled={!form.hasFile}>
          <UploadIcon aria-hidden="true" className="size-4" />
          {t("submit")}
        </Button>
        {sent ? <Button onClick={() => stop.current?.abort()}>{t("stop")}</Button> : null}
      </div>
    </form>
  );
}

/** Uploading to one repository, with the fields its format needs. */
export function UploadScreen() {
  const t = useTranslations("upload");
  const session = useSession();
  const where = parseUpload(usePathname());
  const directory = useSearchParams().get("directory") ?? "";
  const repository = useRepository(where?.repository ?? "");

  // A file let go beside the field would be opened by the browser in place of this
  // page, and what was filled in would be lost. Here a drop does nothing unless a file
  // field takes it.
  useEffect(() => {
    const ignore = (event: DragEvent) => event.preventDefault();
    window.addEventListener("dragover", ignore);
    window.addEventListener("drop", ignore);
    return () => {
      window.removeEventListener("dragover", ignore);
      window.removeEventListener("drop", ignore);
    };
  }, []);

  if (where === null) return <NothingHere />;
  if (repository.isError) {
    return <ErrorState error={repository.error} onRetry={() => void repository.refetch()} />;
  }
  if (!repository.data) return <LoadingState />;
  const found = repository.data;
  return (
    <div className="mx-auto max-w-3xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: found.name, href: browseHref(found.name) },
          { name: t("title"), href: uploadHref(found.name) },
        ]}
      />
      <PageHeader
        named
        title={t("titleTo", { repository: found.name })}
        // A format that takes no upload has no word on how one is made.
        intro={isUploadable(found.format) ? t(`intro.${found.format}`) : undefined}
      />
      {takesUploads(session.data, found) ? (
        <Panel className="p-6">
          <UploadForm repository={found} directory={directory} />
        </Panel>
      ) : (
        <Alert tone="warning" title={t("notHereTitle")}>
          {t(
            found.type !== "hosted"
              ? "notHosted"
              : found.format === "docker"
                ? "notDocker"
                : "notAllowed",
          )}
        </Alert>
      )}
    </div>
  );
}

/** Where to upload to: the hosted repositories this caller may add to. */
export function UploadChooserScreen() {
  const t = useTranslations("upload");
  const session = useSession();
  const repositories = useRepositories();
  if (repositories.isError) {
    return <ErrorState error={repositories.error} onRetry={() => void repositories.refetch()} />;
  }
  const open = (repositories.data?.items ?? []).filter((repository) =>
    takesUploads(session.data, repository),
  );
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={t("title")} intro={t("chooserIntro")} />
      <Panel>
        {!repositories.data ? (
          <LoadingState />
        ) : open.length === 0 ? (
          <EmptyState title={t("nowhereTitle")}>{t("nowhere")}</EmptyState>
        ) : (
          <ul className="flex flex-col">
            {open.map((repository) => (
              <li key={repository.name} className="border-b border-line last:border-b-0">
                <AppLink
                  href={uploadHref(repository.name)}
                  className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-raised"
                >
                  <span className="font-mono font-medium break-all text-ink-cyan">
                    {repository.name}
                  </span>
                  <span className="label-caps text-fg-muted">{repository.format}</span>
                </AppLink>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
