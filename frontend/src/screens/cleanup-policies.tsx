"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { useEveryManagedRepository, useFormats } from "@/lib/administration";
import { isApiError } from "@/lib/api/client";
import type { PolicyContent, PolicyOut, Previewing } from "@/lib/api/types";
import {
  AT_ONCE,
  criteriaInWords,
  useCreatePolicy,
  useDeletePolicy,
  usePolicies,
  usePolicy,
  usePolicyPreview,
  useUpdatePolicy,
} from "@/lib/cleanup";
import { exactTime } from "@/lib/format";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import {
  CLEANUP_POLICIES,
  cleanupPolicyHref,
  isAddressable,
  NEW_CLEANUP_POLICY,
  pageHref,
  pageOf,
  parseCleanupPolicy,
} from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rules, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const MOST_DAYS = 36500;
const EVERY_FORMAT = "*";
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
// How long the form is left alone before what it would remove is asked again (W3).
const SETTLE_MS = 500;
const FIELDS = [
  "name",
  "description",
  "format",
  "updated_days",
  "downloaded_days",
  "release_type",
  "asset_pattern",
  "criteria",
] as const;

function useMayWrite(): boolean {
  const session = useSession();
  return session.data !== undefined && allows(session.data, "admin:cleanup:write");
}

/** The cleanup policies there are (spec 6): each one's format, what it removes, and where. */
export function PoliciesScreen() {
  const t = useTranslations("cleanup");
  const say = useTranslations("cleanup.criteria");
  const page = pageOf(useSearchParams());
  const policies = usePolicies(page);
  const mayWrite = useMayWrite();
  const pages = policies.data === undefined ? undefined : Math.ceil(policies.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(CLEANUP_POLICIES, target);
  const top = usePageFocus<HTMLDivElement>(page, policies.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_CLEANUP_POLICY}>
              <Plus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {policies.isError ? (
        <ErrorState error={policies.error} onRetry={() => void policies.refetch()} />
      ) : !policies.data || beyond ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : policies.data.items.length === 0 ? (
        <Panel>
          <p className="p-6 text-fg-muted">{t("none")}</p>
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
                  <Th>{t("columns.criteria")}</Th>
                  <Th>{t("columns.repositories")}</Th>
                </tr>
              </thead>
              <tbody>
                {policies.data.items.map((policy) => (
                  <tr key={policy.name} className="hover:bg-raised">
                    <Td>
                      {isAddressable(policy.name) ? (
                        <AppLink
                          href={cleanupPolicyHref(policy.name)}
                          className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                        >
                          {policy.name}
                        </AppLink>
                      ) : (
                        <span className="font-mono font-medium text-fg">{policy.name}</span>
                      )}
                    </Td>
                    <Td className="font-mono text-sm">
                      {policy.format === EVERY_FORMAT ? t("everyFormat") : policy.format}
                    </Td>
                    <Td className="break-words">{criteriaInWords(policy, say)}</Td>
                    <Td className="font-mono text-sm break-all text-fg-muted">
                      {policy.repositories.length > 0
                        ? policy.repositories.join(", ")
                        : t("attachedToNone")}
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

/** A form's criteria: each turned on or off, with its value as typed. */
type Draft = {
  name: string;
  description: string;
  format: string;
  updated: boolean;
  updatedDays: string;
  downloaded: boolean;
  downloadedDays: string;
  release: boolean;
  releaseType: "release" | "prerelease";
  pattern: boolean;
  assetPattern: string;
};

function draftOf(policy: PolicyOut | null): Draft {
  return {
    name: "",
    description: policy?.description ?? "",
    format: policy?.format ?? "",
    updated: policy?.updated_days != null,
    updatedDays: String(policy?.updated_days ?? 30),
    downloaded: policy?.downloaded_days != null,
    downloadedDays: String(policy?.downloaded_days ?? 90),
    release: policy?.release_type != null,
    releaseType: policy?.release_type === "release" ? "release" : "prerelease",
    pattern: policy?.asset_pattern != null,
    assetPattern: policy?.asset_pattern ?? "",
  };
}

/** What the form says to send: what is turned off is null; release type only where it can be. */
function contentOf(draft: Draft, hasReleases: boolean): PolicyContent & { format: string } {
  const days = (on: boolean, typed: string) => (on ? Number(typed.trim()) : null);
  return {
    description: draft.description.trim(),
    format: draft.format,
    updated_days: days(draft.updated, draft.updatedDays),
    downloaded_days: days(draft.downloaded, draft.downloadedDays),
    release_type: draft.release && hasReleases ? draft.releaseType : null,
    asset_pattern: draft.pattern ? draft.assetPattern : null,
  };
}

type Problems = Partial<Record<(typeof FIELDS)[number], string>>;

/** What is wrong with a form before it is sent: none where the server may still say so. */
function useProblems(draft: Draft, creating: boolean, hasReleases: boolean): Problems {
  const t = useTranslations("cleanup");
  const problems: Problems = {};
  if (creating) {
    if (!NAME.test(draft.name)) problems.name = t("nameRule");
    else if (!isAddressable(draft.name)) problems.name = t("nameDots");
  }
  const daysWrong = (typed: string) => {
    const days = Number(typed.trim());
    return typed.trim() === "" || !Number.isInteger(days) || days < 1 || days > MOST_DAYS;
  };
  if (draft.updated && daysWrong(draft.updatedDays)) problems.updated_days = t("daysRule");
  if (draft.downloaded && daysWrong(draft.downloadedDays)) {
    problems.downloaded_days = t("daysRule");
  }
  const any = draft.updated || draft.downloaded || (draft.release && hasReleases) || draft.pattern;
  if (!any) problems.criteria = t("criterionNeeded");
  return problems;
}

/** What a value is once it has not changed for a while. */
function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/**
 * What a policy, as the form holds it, would remove from a repository of its format now
 * (W3): asked again once the form has been left alone, never while it has a problem.
 */
function PolicyPreview({ wanted }: { wanted: (PolicyContent & { format: string }) | null }) {
  const t = useTranslations("cleanup");
  const pager = useTranslations("pager");
  const formats = wanted?.format ?? "";
  const repositories = useEveryManagedRepository();
  const choices = (repositories.data ?? [])
    .filter((found) => found.type !== "group")
    .filter((found) => formats === EVERY_FORMAT || found.format === formats)
    .map((found) => found.name)
    .sort();
  const [chosen, setChosen] = useState<string | null>(null);
  const repository = chosen !== null && choices.includes(chosen) ? chosen : (choices[0] ?? null);
  // What is asked, as text: the same policy is the same text, however often it is drawn.
  const asked =
    wanted === null || repository === null ? "" : JSON.stringify({ ...wanted, repository });
  const key = useSettled(asked, SETTLE_MS);
  const settled = key === "" ? null : (JSON.parse(key) as Previewing);
  // A page of what was asked before is no page of what is asked now: it starts at the first.
  const [paging, setPaging] = useState({ key, page: 1 });
  const page = paging.key === key ? paging.page : 1;
  const setPage = (target: number) => setPaging({ key, page: target });
  // Asked by what has settled alone: a query turned off and on again would be asked anew.
  const preview = usePolicyPreview(settled, page);
  const pages = preview.data ? Math.max(1, Math.ceil(preview.data.total / AT_ONCE)) : 1;

  return (
    <section aria-labelledby="cleanup-preview" className="flex flex-col gap-4">
      <h2 id="cleanup-preview" className={H2}>
        {t("previewTitle")}
      </h2>
      <p className="text-fg-muted">{t("previewIntro")}</p>
      {wanted === null ? (
        <Alert tone="info">{t("previewProblem")}</Alert>
      ) : repositories.data && choices.length === 0 ? (
        <p className="text-fg-muted">{t("previewNoRepository")}</p>
      ) : (
        <>
          <SelectField
            label={t("previewRepository")}
            className="max-w-sm"
            value={repository ?? ""}
            onChange={(event) => setChosen(event.target.value)}
            choices={choices.map((name) => ({ value: name, label: name }))}
          />
          {preview.isError ? (
            <ErrorState error={preview.error} />
          ) : !preview.data ? (
            <LoadingState />
          ) : preview.data.total === 0 ? (
            <p className="text-fg-muted">{t("previewNothing", { repository: repository ?? "" })}</p>
          ) : (
            <>
              <p className="font-medium text-fg">
                {t("previewTotal", { total: preview.data.total })}
              </p>
              <Table caption={t("previewTable")}>
                <thead>
                  <tr>
                    <Th>{t("previewColumns.name")}</Th>
                    <Th>{t("previewColumns.version")}</Th>
                    <Th>{t("previewColumns.modified")}</Th>
                    <Th>{t("previewColumns.downloaded")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.items.map((found) => (
                    <tr key={found.id}>
                      <Td className="font-mono text-sm break-all">
                        {found.namespace ? `${found.namespace}/${found.name}` : found.name}
                      </Td>
                      <Td className="font-mono text-sm break-all">{found.version}</Td>
                      <Td>{exactTime(new Date(found.modified))}</Td>
                      <Td>
                        {found.last_downloaded
                          ? exactTime(new Date(found.last_downloaded))
                          : t("never")}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {pages > 1 ? (
                <nav aria-label={pager("label")} className="flex items-center gap-3">
                  <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                    {pager("previous")}
                  </Button>
                  <span className="text-sm text-fg-muted">
                    {pager("position", { page, pages })}
                  </span>
                  <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                    {pager("next")}
                  </Button>
                </nav>
              ) : null}
            </>
          )}
        </>
      )}
    </section>
  );
}

/**
 * The form of a policy, new or not: its criteria, each said wrong where the server says
 * so, and beside them what it would remove, as it is typed.
 */
function PolicyForm({
  policy,
  saving,
  error,
  onSave,
  saveLabel,
  readOnly = false,
}: {
  /** The policy as it is, or null for one that is not there yet, which also has a name. */
  policy: PolicyOut | null;
  saving: boolean;
  error: unknown;
  onSave: (content: PolicyContent & { name: string; format: string }) => void;
  saveLabel: string;
  readOnly?: boolean;
}) {
  const t = useTranslations("cleanup");
  const formats = useFormats();
  const [draft, setDraft] = useState<Draft>(() => draftOf(policy));
  const change = (changes: Partial<Draft>) => setDraft((was) => ({ ...was, ...changes }));
  const { form, tried, attempt } = useAttempts(error);
  const creating = policy === null;
  const format = draft.format || formats.data?.[0]?.name || "";
  const hasReleases =
    format !== EVERY_FORMAT &&
    (formats.data?.find((found) => found.name === format)?.has_prereleases ?? false);
  const problems = useProblems(draft, creating, hasReleases);
  const refused = refusalsOf(error, FIELDS);
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const said = (field: (typeof FIELDS)[number]) =>
    tried ? (problems[field] ?? (field === "name" ? taken : null) ?? refused.at[field]) : undefined;
  const content = contentOf({ ...draft, format }, hasReleases);
  const ownProblem = Object.keys(problems).length > 0;
  const criteriaWrong = Object.keys(problems).some((field) => field !== "name");

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    if (ownProblem) return;
    onSave({ ...content, name: draft.name });
  }

  const criterion = (label: string) => ({ criterion: label });
  return (
    <div className="flex flex-col gap-8">
      <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
        <fieldset disabled={readOnly} className="flex min-w-0 flex-col gap-6 border-0 p-0">
          <div className="grid gap-4 sm:grid-cols-2">
            {creating ? (
              <TextField
                label={t("fields.name")}
                hint={t("hints.name")}
                required
                spellCheck={false}
                autoComplete="off"
                value={draft.name}
                error={said("name")}
                onChange={(event) => change({ name: event.target.value })}
              />
            ) : null}
            <TextField
              label={t("fields.description")}
              maxLength={255}
              value={draft.description}
              error={said("description")}
              onChange={(event) => change({ description: event.target.value })}
            />
            {creating ? (
              <SelectField
                label={t("fields.format")}
                value={format}
                onChange={(event) => change({ format: event.target.value })}
                choices={[
                  ...(formats.data ?? []).map((found) => ({
                    value: found.name,
                    label: found.name,
                  })),
                  { value: EVERY_FORMAT, label: t("everyFormat") },
                ]}
              />
            ) : (
              <Facts>
                <Fact name={t("fields.format")} mono>
                  {format === EVERY_FORMAT ? t("everyFormat") : format}
                </Fact>
              </Facts>
            )}
          </div>
          <div className="flex flex-col gap-4">
            <CheckboxField
              label={t("fields.updated")}
              hint={t("hints.updated")}
              checked={draft.updated}
              onChange={(event) => change({ updated: event.target.checked })}
            />
            {draft.updated ? (
              <TextField
                label={t("fields.days", criterion(t("fields.updated")))}
                plainLabel
                className="ml-7 max-w-48"
                type="number"
                min={1}
                max={MOST_DAYS}
                value={draft.updatedDays}
                error={said("updated_days")}
                onChange={(event) => change({ updatedDays: event.target.value })}
              />
            ) : null}
            <CheckboxField
              label={t("fields.downloaded")}
              hint={t("hints.downloaded")}
              checked={draft.downloaded}
              onChange={(event) => change({ downloaded: event.target.checked })}
            />
            {draft.downloaded ? (
              <TextField
                label={t("fields.days", criterion(t("fields.downloaded")))}
                plainLabel
                className="ml-7 max-w-48"
                type="number"
                min={1}
                max={MOST_DAYS}
                value={draft.downloadedDays}
                error={said("downloaded_days")}
                onChange={(event) => change({ downloadedDays: event.target.value })}
              />
            ) : null}
            {hasReleases ? (
              <>
                <CheckboxField
                  label={t("fields.releaseType")}
                  checked={draft.release}
                  onChange={(event) => change({ release: event.target.checked })}
                />
                {draft.release ? (
                  <SelectField
                    label={t("fields.which", criterion(t("fields.releaseType")))}
                    className="ml-7 max-w-48"
                    value={draft.releaseType}
                    onChange={(event) =>
                      change({
                        releaseType: event.target.value === "release" ? "release" : "prerelease",
                      })
                    }
                    choices={[
                      { value: "release", label: t("releaseTypes.release") },
                      { value: "prerelease", label: t("releaseTypes.prerelease") },
                    ]}
                  />
                ) : null}
              </>
            ) : null}
            <CheckboxField
              label={t("fields.pattern")}
              hint={t("hints.pattern")}
              checked={draft.pattern}
              onChange={(event) => change({ pattern: event.target.checked })}
            />
            {draft.pattern ? (
              <TextField
                label={t("fields.expression", criterion(t("fields.pattern")))}
                plainLabel
                className="ml-7"
                spellCheck={false}
                value={draft.assetPattern}
                error={said("asset_pattern")}
                onChange={(event) => change({ assetPattern: event.target.value })}
              />
            ) : null}
            {said("criteria") ? (
              <p role="alert" className="text-sm text-bad">
                {said("criteria")}
              </p>
            ) : null}
            {tried && said("release_type") ? (
              <p role="alert" className="text-sm text-bad">
                {said("release_type")}
              </p>
            ) : null}
          </div>
          {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
        </fieldset>
        {readOnly ? null : (
          <div>
            <Button type="submit" variant="primary" busy={saving}>
              {saveLabel}
            </Button>
          </div>
        )}
      </form>
      {/* A name not yet right does not stop the preview: what it removes is the criteria's. */}
      <PolicyPreview wanted={criteriaWrong ? null : content} />
    </div>
  );
}

/** A new cleanup policy. */
export function NewPolicyScreen() {
  const t = useTranslations("cleanup");
  const router = useRouter();
  const notify = useNotify();
  const create = useCreatePolicy();
  const mayCreate = useMayWrite();
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("title")}
        crumbs={[
          { name: t("title"), href: CLEANUP_POLICIES },
          { name: t("newTitle"), href: NEW_CLEANUP_POLICY },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      {mayCreate ? null : <Alert tone="warning">{t("mayNotCreate")}</Alert>}
      <Panel className="p-6" hidden={!mayCreate}>
        <PolicyForm
          policy={null}
          saving={create.isPending}
          error={create.error}
          saveLabel={t("create")}
          onSave={(content) =>
            create.mutate(content, {
              onSuccess: (made) => {
                notify(t("created", { name: made.name }));
                router.push(cleanupPolicyHref(made.name));
              },
            })
          }
        />
      </Panel>
    </div>
  );
}

function Edit({ policy, readOnly }: { policy: PolicyOut; readOnly: boolean }) {
  const t = useTranslations("cleanup");
  const notify = useNotify();
  const update = useUpdatePolicy(policy.name);
  return (
    <Panel className="p-6">
      <PolicyForm
        policy={policy}
        readOnly={readOnly}
        saving={update.isPending}
        error={update.error}
        saveLabel={t("save")}
        onSave={(content) =>
          update.mutate(
            {
              description: content.description,
              format: content.format,
              updated_days: content.updated_days,
              downloaded_days: content.downloaded_days,
              release_type: content.release_type,
              asset_pattern: content.asset_pattern,
            },
            { onSuccess: () => notify(t("saved", { name: policy.name })) },
          )
        }
      />
    </Panel>
  );
}

/** One cleanup policy: what it removes, what it would remove now, changing and deleting it. */
export function PolicyScreen() {
  const t = useTranslations("cleanup");
  const router = useRouter();
  const notify = useNotify();
  const where = parseCleanupPolicy(usePathname());
  const mayWrite = useMayWrite();
  const remove = useDeletePolicy();
  // Once deleted, the policy is not asked for again: there is none to answer with.
  const policy = usePolicy(remove.isSuccess ? null : (where?.name ?? null));
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (policy.isError) {
    return <ErrorState error={policy.error} onRetry={() => void policy.refetch()} />;
  }
  if (!policy.data || !policy.isFetchedAfterMount) return <LoadingState />;

  const found = policy.data;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("title")}
          crumbs={[
            { name: t("title"), href: CLEANUP_POLICIES },
            { name: found.name, href: cleanupPolicyHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} />
      </div>
      <Edit policy={found} readOnly={!mayWrite} />
      {mayWrite ? (
        <Panel className="p-6">
          <h2 className={H2}>{t("deleteTitle")}</h2>
          <p className="mb-4 text-fg-muted">{t("deleteIntro")}</p>
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
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(found.name, {
                onSuccess: () => {
                  notify(t("deleted", { name: found.name }));
                  router.replace(CLEANUP_POLICIES);
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {found.repositories.length > 0
              ? t("deleteBody", { repositories: found.repositories.join(", ") })
              : t("deleteBodyNone")}
          </ConfirmDialog>
        </Panel>
      ) : null}
    </div>
  );
}
