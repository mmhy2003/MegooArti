"use client";

import { FolderOpen, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { MemberList } from "@/components/member-list";
import { Alert, StatusTag } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, ChoiceGroup, SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import {
  useCreateRepository,
  useDeleteRepository,
  useEveryBlobStore,
  useEveryManagedRepository,
  useInvalidateCache,
  useManagedRepository,
  useRebuildIndex,
  useUpdateRepository,
} from "@/lib/administration";
import { isApiError } from "@/lib/api/client";
import type { RepositoryOut } from "@/lib/api/types";
import { useRepository } from "@/lib/content";
import { useAttempts } from "@/lib/focus";
import {
  browseHref,
  MANAGE_REPOSITORIES,
  NEW_REPOSITORY,
  parseRepositorySettings,
  repositorySettingsHref,
} from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  AUTH_TYPES,
  createBody,
  DEFAULT_BLOB_STORE,
  DEPLOYMENT_POLICIES,
  draftOf,
  EMPTY,
  FORMATS,
  hasMavenSettings,
  LAYOUT_POLICIES,
  problemsOf,
  TYPES,
  updateBody,
  VERSION_POLICIES,
  type Draft,
  type RepositoryType,
} from "@/lib/repository-form";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
const SECTION = "flex min-w-0 flex-col gap-4 rounded-sm border border-line p-4";
const LEGEND = "label-caps px-1 text-fg-muted";

// The server's own names for what it refuses, the closest first: a refusal is put at
// the first of these it is about, or under.
const REFUSED_AT = [
  "name",
  "blob_store",
  "hosted.deployment_policy",
  "proxy.remote_url",
  "proxy.content_max_age_minutes",
  "proxy.metadata_max_age_minutes",
  "proxy.negative_cache.ttl_minutes",
  "proxy.remote_auth.username",
  "proxy.remote_auth.secret",
  "group.members",
  "format_config.version_policy",
  "format_config.layout_policy",
] as const;

function useMay(): (permission: string) => boolean {
  const session = useSession();
  return (permission) => session.data !== undefined && allows(session.data, permission);
}

/**
 * The form of a repository, new or not: one page that grows (R2). The format and the
 * type decide which parts it has. `repository` is the one that is there, or null for a
 * new one, which also has what can be chosen only once. `onSave` is given what the
 * form holds once nothing is wrong with it, and answers with the repository as the
 * server then has it, from which the form starts again.
 */
function RepositoryForm({
  repository,
  saving,
  error,
  onSave,
  saveLabel,
  mayWrite,
}: {
  repository: RepositoryOut | null;
  saving: boolean;
  error: unknown;
  onSave: (draft: Draft) => Promise<RepositoryOut | null>;
  saveLabel: string;
  mayWrite: boolean;
}) {
  const t = useTranslations("manage");
  const may = useMay();
  const creating = repository === null;
  const [draft, setDraft] = useState<Draft>(() => (repository ? draftOf(repository) : EMPTY));
  const set = (change: Partial<Draft>) => setDraft((held) => ({ ...held, ...change }));
  const { form, tried, attempt } = useAttempts(error);
  const storesReadable = may("admin:blobstores:read");
  const stores = useEveryBlobStore(creating && storesReadable);
  // Asked for only where they are chosen from: a group's members.
  const others = useEveryManagedRepository(draft.type === "group");

  const own = problemsOf(draft, creating);
  const refused = refusalsOf(error, REFUSED_AT);
  // A name another repository has: said at the name.
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const wrong = (field: keyof typeof own, server?: string) =>
    tried ? (own[field] ? t(`problems.${own[field]}`) : server) : undefined;

  async function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    if (Object.keys(own).length > 0) return;
    const saved = await onSave(draft);
    // What the server holds now: its own spelling of the remote, and no secret typed.
    if (saved !== null) setDraft(draftOf(saved));
  }

  const { type } = draft;
  const storeNames = Array.from(
    new Set([DEFAULT_BLOB_STORE, ...(stores.data?.map((store) => store.name) ?? [])]),
  );
  // Not known until they were had: an empty list would say that there are none.
  const candidates =
    others.data
      ?.filter((other) => other.format === draft.format && other.name !== repository?.name)
      .map((other) => other.name) ?? null;
  const option = <Value extends string>(group: string, values: readonly Value[]) =>
    values.map((value) => ({
      value,
      label: t(`${group}.${value}` as "types.hosted"),
      hint: t(`${group}Hints.${value}` as "typesHints.hosted"),
    }));

  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-6 border-0 p-0">
        {creating ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label={t("fields.format")}
                value={draft.format}
                // The members of a group are of its format: those of another are none.
                onChange={(event) => set({ format: event.target.value, members: [] })}
                choices={FORMATS.map((format) => ({ value: format, label: format }))}
              />
              <TextField
                label={t("fields.name")}
                hint={t("hints.name")}
                required
                spellCheck={false}
                autoComplete="off"
                value={draft.name}
                error={wrong("name", taken ?? refused.at.name)}
                onChange={(event) => set({ name: event.target.value })}
              />
            </div>
            <ChoiceGroup
              legend={t("fields.type")}
              value={type}
              onChange={(value) => set({ type: value as RepositoryType })}
              options={option("types", TYPES)}
            />
          </>
        ) : null}
        <CheckboxField
          label={t("fields.online")}
          hint={t("hints.online")}
          checked={draft.online}
          onChange={(event) => set({ online: event.target.checked })}
        />
        {creating && type !== "group" ? (
          <div className="flex flex-col gap-1.5">
            <SelectField
              label={t("fields.blobStore")}
              value={draft.blobStore}
              onChange={(event) => set({ blobStore: event.target.value })}
              choices={storeNames.map((name) => ({ value: name, label: name }))}
            />
            <p className="text-sm text-fg-subtle">
              {storesReadable ? t("hints.blobStore") : t("hints.blobStoreUnreadable")}
            </p>
            {stores.isError ? (
              <ErrorState error={stores.error} onRetry={() => void stores.refetch()} />
            ) : null}
            {refused.at.blob_store ? <Alert tone="danger">{refused.at.blob_store}</Alert> : null}
          </div>
        ) : null}

        {type === "hosted" ? (
          <fieldset className={SECTION}>
            <legend className={LEGEND}>{t("sections.hosted")}</legend>
            <ChoiceGroup
              legend={t("fields.deploymentPolicy")}
              value={draft.deploymentPolicy}
              onChange={(value) => set({ deploymentPolicy: value })}
              options={option("policies", DEPLOYMENT_POLICIES)}
            />
            {refused.at["hosted.deployment_policy"] ? (
              <Alert tone="danger">{refused.at["hosted.deployment_policy"]}</Alert>
            ) : null}
          </fieldset>
        ) : null}

        {type === "proxy" ? (
          <>
            <fieldset className={SECTION}>
              <legend className={LEGEND}>{t("sections.remote")}</legend>
              <TextField
                label={t("fields.remoteUrl")}
                hint={t("hints.remoteUrl")}
                type="url"
                required
                spellCheck={false}
                autoComplete="off"
                value={draft.remoteUrl}
                error={wrong("remoteUrl", refused.at["proxy.remote_url"])}
                onChange={(event) => set({ remoteUrl: event.target.value })}
              />
              <SelectField
                label={t("fields.authType")}
                value={draft.authType}
                onChange={(event) => set({ authType: event.target.value })}
                choices={AUTH_TYPES.map((kind) => ({ value: kind, label: t(`auth.${kind}`) }))}
              />
              {draft.authType === "basic" ? (
                <TextField
                  label={t("fields.authUsername")}
                  spellCheck={false}
                  autoComplete="off"
                  value={draft.authUsername}
                  error={wrong("authUsername", refused.at["proxy.remote_auth.username"])}
                  onChange={(event) => set({ authUsername: event.target.value })}
                />
              ) : null}
              {draft.authType !== "none" ? (
                <TextField
                  label={draft.authType === "basic" ? t("fields.password") : t("fields.token")}
                  // Never shown: the server gives it back to nobody (R4).
                  hint={draft.hasSecret ? t("hints.secretStored") : t("hints.secret")}
                  type="password"
                  autoComplete="new-password"
                  spellCheck={false}
                  value={draft.authSecret}
                  error={wrong("authSecret", refused.at["proxy.remote_auth.secret"])}
                  onChange={(event) => set({ authSecret: event.target.value })}
                />
              ) : null}
            </fieldset>
            <fieldset className={SECTION}>
              <legend className={LEGEND}>{t("sections.cache")}</legend>
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField
                  label={t("fields.contentMaxAge")}
                  hint={t("hints.maxAge")}
                  inputMode="numeric"
                  value={draft.contentMaxAge}
                  error={wrong("contentMaxAge", refused.at["proxy.content_max_age_minutes"])}
                  onChange={(event) => set({ contentMaxAge: event.target.value })}
                />
                <TextField
                  label={t("fields.metadataMaxAge")}
                  hint={t("hints.metadataMaxAge")}
                  inputMode="numeric"
                  value={draft.metadataMaxAge}
                  error={wrong("metadataMaxAge", refused.at["proxy.metadata_max_age_minutes"])}
                  onChange={(event) => set({ metadataMaxAge: event.target.value })}
                />
              </div>
              <CheckboxField
                label={t("fields.negativeCache")}
                hint={t("hints.negativeCache")}
                checked={draft.negativeCache}
                onChange={(event) => set({ negativeCache: event.target.checked })}
              />
              {draft.negativeCache ? (
                <TextField
                  label={t("fields.negativeCacheTtl")}
                  inputMode="numeric"
                  value={draft.negativeCacheTtl}
                  error={wrong("negativeCacheTtl", refused.at["proxy.negative_cache.ttl_minutes"])}
                  onChange={(event) => set({ negativeCacheTtl: event.target.value })}
                />
              ) : null}
            </fieldset>
            <fieldset className={SECTION}>
              <legend className={LEGEND}>{t("sections.blocking")}</legend>
              <CheckboxField
                label={t("fields.autoBlock")}
                hint={t("hints.autoBlock")}
                checked={draft.autoBlock}
                onChange={(event) => set({ autoBlock: event.target.checked })}
              />
              <CheckboxField
                label={t("fields.blocked")}
                hint={t("hints.blocked")}
                checked={draft.blocked}
                onChange={(event) => set({ blocked: event.target.checked })}
              />
            </fieldset>
          </>
        ) : null}

        {type === "group" ? (
          <div className="flex flex-col gap-3 rounded-sm border border-line p-4">
            <MemberList
              legend={t("fields.members")}
              hint={t("hints.members")}
              members={draft.members}
              onChange={(members) => set({ members })}
              candidates={candidates}
              error={refused.at["group.members"]}
            />
            {others.isError ? (
              <ErrorState error={others.error} onRetry={() => void others.refetch()} />
            ) : candidates === null ? (
              <LoadingState className="p-2" />
            ) : null}
          </div>
        ) : null}

        {hasMavenSettings(draft) ? (
          <fieldset className={SECTION}>
            <legend className={LEGEND}>{t("sections.maven")}</legend>
            {creating ? (
              <ChoiceGroup
                legend={t("fields.versionPolicy")}
                value={draft.versionPolicy}
                onChange={(value) => set({ versionPolicy: value })}
                options={option("versions", VERSION_POLICIES)}
              />
            ) : null}
            <ChoiceGroup
              legend={t("fields.layoutPolicy")}
              value={draft.layoutPolicy}
              onChange={(value) => set({ layoutPolicy: value })}
              options={option("layouts", LAYOUT_POLICIES)}
            />
            {refused.at["format_config.layout_policy"] ? (
              <Alert tone="danger">{refused.at["format_config.layout_policy"]}</Alert>
            ) : null}
          </fieldset>
        ) : null}
      </fieldset>
      {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
      {mayWrite ? (
        <div>
          <Button type="submit" variant="primary" busy={saving}>
            {saveLabel}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

/** A new repository (R2, R13). */
export function NewRepositoryScreen() {
  const t = useTranslations("manage");
  const router = useRouter();
  const notify = useNotify();
  const may = useMay();
  const create = useCreateRepository();
  const mayCreate = may("admin:repositories:write");
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: MANAGE_REPOSITORIES },
          { name: t("newTitle"), href: NEW_REPOSITORY },
        ]}
      />
      <PageHeader title={t("newTitle")} intro={t("newIntro")} />
      {mayCreate ? (
        <Panel className="p-6">
          <RepositoryForm
            repository={null}
            mayWrite
            saving={create.isPending}
            error={create.error}
            saveLabel={t("create")}
            onSave={async (draft) => {
              try {
                const made = await create.mutateAsync(createBody(draft));
                // What was sent may have had a secret in it: the store lets go of it.
                create.reset();
                notify(t("created", { name: made.name }));
                router.push(repositorySettingsHref(made.name));
              } catch {
                // Said by the form, from the request's own state.
              }
              return null;
            }}
          />
        </Panel>
      ) : (
        // The address can be typed by anybody. The server would refuse what was filled in.
        <Alert tone="warning">{t("mayNotCreate")}</Alert>
      )}
    </div>
  );
}

/** What a proxy last met at its remote (R7), and a way to have everything checked again. */
function ProxyState({ repository, mayWrite }: { repository: RepositoryOut; mayWrite: boolean }) {
  const t = useTranslations("manage");
  const notify = useNotify();
  const invalidate = useInvalidateCache(repository.name);
  const status = repository.status;
  // Read once, when the state is shown: a block that ends while the page is open is
  // seen to have ended the next time the page is.
  const [now] = useState(() => Date.now());
  const until = status?.auto_blocked_until ?? null;
  const waiting = until !== null && new Date(until).getTime() > now;
  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("stateTitle")}</h2>
      <Facts className="mb-5">
        <Fact name={t("state.remote")}>
          {status?.blocked ? (
            <StatusTag tone="warning">{t("state.blocked")}</StatusTag>
          ) : waiting ? (
            <StatusTag tone="warning">{t("state.waiting")}</StatusTag>
          ) : (
            <StatusTag tone="success">{t("state.reachable")}</StatusTag>
          )}
        </Fact>
        {waiting ? (
          <Fact name={t("state.until")}>
            <Time value={until} />
          </Fact>
        ) : null}
        <Fact name={t("state.failures")}>{status?.failures ?? 0}</Fact>
        {status?.last_error ? (
          <Fact name={t("state.lastError")} mono>
            {status.last_error}
          </Fact>
        ) : null}
      </Facts>
      {invalidate.isError ? <ErrorState error={invalidate.error} className="mb-4" /> : null}
      {mayWrite ? (
        <>
          <p className="mb-3 text-fg-muted">{t("checkAgainIntro")}</p>
          <Button
            busy={invalidate.isPending}
            onClick={() =>
              invalidate.mutate(undefined, {
                onSuccess: () => notify(t("checkedAgain", { name: repository.name })),
              })
            }
          >
            <RefreshCw aria-hidden="true" className="size-4" />
            {t("checkAgain")}
          </Button>
        </>
      ) : null}
    </Panel>
  );
}

/** Going through a repository again (R8). It is done in the request: the button waits for it. */
function RebuildIndex({ repository }: { repository: RepositoryOut }) {
  const t = useTranslations("manage");
  const rebuild = useRebuildIndex(repository.name);
  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("rebuildTitle")}</h2>
      <p className="mb-4 text-fg-muted">{t("rebuildIntro")}</p>
      {rebuild.isError ? <ErrorState error={rebuild.error} className="mb-4" /> : null}
      {rebuild.data ? (
        <Alert tone="success" title={t("rebuilt")} className="mb-4">
          {t("rebuiltFound", rebuild.data)}
        </Alert>
      ) : null}
      <Button busy={rebuild.isPending} onClick={() => rebuild.mutate()}>
        <RefreshCw aria-hidden="true" className="size-4" />
        {t("rebuild")}
      </Button>
    </Panel>
  );
}

/** One repository as an administrator sees it: its settings, its state, and deleting it. */
export function RepositorySettingsScreen() {
  const t = useTranslations("manage");
  const router = useRouter();
  const notify = useNotify();
  const may = useMay();
  const where = parseRepositorySettings(usePathname());
  const remove = useDeleteRepository();
  // Once deleted, the repository is not asked for again: there is none to answer with.
  const repository = useManagedRepository(remove.isSuccess ? null : (where?.name ?? null));
  const update = useUpdateRepository(where?.name ?? "");
  // The address its clients use is the browsing API's to say: a registry has one of its
  // own, which the path of the others is not. Whoever may not browse it is told none.
  const view = useRepository(remove.isSuccess ? "" : (where?.name ?? ""));
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (repository.isError) {
    return <ErrorState error={repository.error} onRetry={() => void repository.refetch()} />;
  }
  // The form is filled once, when it opens, so it opens on an answer that came after
  // the page did (A23).
  if (!repository.data || !repository.isFetchedAfterMount) return <LoadingState />;

  const found = repository.data;
  const mayWrite = may("admin:repositories:write");
  const typeName = (TYPES as readonly string[]).includes(found.type)
    ? t(`types.${found.type as RepositoryType}`)
    : found.type;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: MANAGE_REPOSITORIES },
            { name: found.name, href: repositorySettingsHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} intro={t("settingsOf")}>
          <Button asChild size="sm" variant="ghost">
            <AppLink href={browseHref(found.name)}>
              <FolderOpen aria-hidden="true" className="size-4" />
              {t("browse")}
            </AppLink>
          </Button>
        </PageHeader>
      </div>
      <Panel className="p-6">
        {/* What cannot change is a fact, not a field (R3). */}
        <Facts className="mb-6">
          <Fact name={t("fields.format")}>{found.format}</Fact>
          <Fact name={t("fields.type")}>{typeName}</Fact>
          {found.blob_store ? (
            <Fact name={t("fields.blobStore")} mono>
              {found.blob_store}
            </Fact>
          ) : null}
          {hasMavenSettings(draftOf(found)) ? (
            <Fact name={t("fields.versionPolicy")}>
              {String(found.format_config.version_policy ?? "")}
            </Fact>
          ) : null}
          {view.data ? (
            <Fact name={t("fields.address")} copy={view.data.url} mono>
              {view.data.url}
            </Fact>
          ) : null}
        </Facts>
        <RepositoryForm
          repository={found}
          mayWrite={mayWrite}
          saving={update.isPending}
          error={update.error}
          saveLabel={t("save")}
          onSave={async (draft) => {
            try {
              const saved = await update.mutateAsync(updateBody(draft));
              notify(t("saved", { name: saved.name }));
              // What was sent may have had a secret in it: the store lets go of it.
              update.reset();
              return saved;
            } catch {
              return null; // said by the form, from the request's own state
            }
          }}
        />
      </Panel>
      {found.type === "proxy" ? <ProxyState repository={found} mayWrite={mayWrite} /> : null}
      {mayWrite && found.type !== "group" ? <RebuildIndex repository={found} /> : null}
      {mayWrite ? (
        <Panel className="p-6">
          <h2 className={H2}>{t("deleteTitle")}</h2>
          <p className="mb-4 text-fg-muted">
            {found.type === "group" ? t("deleteIntroGroup") : t("deleteIntro")}
          </p>
          {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
          <Button
            variant="danger"
            onClick={() => {
              remove.reset();
              setAsking(true);
            }}
          >
            <Trash2 aria-hidden="true" className="size-4" />
            {t("delete")}
          </Button>
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title={t("deleteAsk", { name: found.name })}
            confirmLabel={t("delete")}
            mustType={found.name}
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(found.name, {
                onSuccess: () => {
                  notify(t("deleted", { name: found.name }));
                  router.replace(MANAGE_REPOSITORIES);
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {found.type === "group" ? t("deleteBodyGroup") : t("deleteBody")}
          </ConfirmDialog>
        </Panel>
      ) : null}
    </div>
  );
}
