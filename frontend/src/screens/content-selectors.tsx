"use client";

import { Check, FlaskConical, Plus, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FORMATS } from "@/components/permission-rows";
import { Alert, StatusTag } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager } from "@/components/ui/details";
import { TextAreaField, TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { SelectorOut } from "@/lib/api/types";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import {
  CONTENT_SELECTORS,
  isAddressable,
  NEW_SELECTOR,
  pageHref,
  pageOf,
  parseSelector,
  selectorHref,
} from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  AT_ONCE,
  useCreateSelector,
  useDeleteSelector,
  usePreview,
  useSelector,
  useSelectors,
  useUpdateSelector,
} from "@/lib/selectors";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rule for a selector's name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
// As many paths as one preview takes.
const MOST_PATHS = 100;

function useMayWrite(): boolean {
  const session = useSession();
  return session.data !== undefined && allows(session.data, "admin:selectors:write");
}

/** The content selectors there are (spec 10): what each is called, and what it matches. */
export function SelectorsScreen() {
  const t = useTranslations("selectors");
  const page = pageOf(useSearchParams());
  const selectors = useSelectors(page);
  const mayWrite = useMayWrite();
  const pages =
    selectors.data === undefined ? undefined : Math.ceil(selectors.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(CONTENT_SELECTORS, target);
  const top = usePageFocus<HTMLDivElement>(page, selectors.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_SELECTOR}>
              <Plus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {selectors.isError ? (
        <ErrorState error={selectors.error} onRetry={() => void selectors.refetch()} />
      ) : !selectors.data || beyond ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : selectors.data.items.length === 0 ? (
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
                  <Th>{t("columns.description")}</Th>
                  <Th>{t("columns.expression")}</Th>
                </tr>
              </thead>
              <tbody>
                {selectors.data.items.map((selector) => (
                  <tr key={selector.name} className="hover:bg-raised">
                    <Td>
                      {isAddressable(selector.name) ? (
                        <AppLink
                          href={selectorHref(selector.name)}
                          className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                        >
                          {selector.name}
                        </AppLink>
                      ) : (
                        <span className="font-mono font-medium text-fg">{selector.name}</span>
                      )}
                    </Td>
                    <Td className="break-words text-fg-muted">{selector.description}</Td>
                    <Td className="font-mono text-xs break-all">{selector.expression}</Td>
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

/**
 * Tries an expression against paths, a line each, in a repository of a format: which
 * it matches is said beside each. Nothing is kept. What does not parse is said at the
 * expression, through `onRefused`.
 */
function PreviewPanel({
  expression,
  onRefused,
}: {
  expression: string;
  onRefused: (said: string | undefined) => void;
}) {
  const t = useTranslations("selectors");
  const preview = usePreview();
  const [format, setFormat] = useState("maven");
  const [typed, setTyped] = useState("");
  const paths = typed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const tooMany = paths.length > MOST_PATHS ? t("tooManyPaths", { most: MOST_PATHS }) : undefined;

  function run() {
    if (expression.trim() === "" || paths.length === 0 || tooMany) return;
    preview.mutate(
      { expression, format, paths },
      {
        onSuccess: () => onRefused(undefined),
        onError: (error) => onRefused(refusalsOf(error, ["expression"]).at.expression),
      },
    );
  }

  const refused = refusalsOf(preview.error, ["expression"]);
  return (
    <section aria-labelledby="selector-preview" className="flex flex-col gap-4">
      <h2 id="selector-preview" className={H2}>
        {t("previewTitle")}
      </h2>
      <p className="text-fg-muted">{t("previewIntro")}</p>
      <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
        <SelectField
          label={t("fields.format")}
          value={format}
          onChange={(event) => setFormat(event.target.value)}
          choices={FORMATS.map((value) => ({ value, label: value }))}
        />
        <TextAreaField
          label={t("fields.paths")}
          hint={t("hints.paths")}
          rows={4}
          spellCheck={false}
          className="font-mono text-sm"
          value={typed}
          error={tooMany}
          onChange={(event) => setTyped(event.target.value)}
        />
      </div>
      <div>
        <Button
          onClick={run}
          busy={preview.isPending}
          disabled={expression.trim() === "" || paths.length === 0}
        >
          <FlaskConical aria-hidden="true" className="size-4" />
          {t("preview")}
        </Button>
      </div>
      {preview.isError && refused.elsewhere ? <ErrorState error={preview.error} /> : null}
      {preview.data ? (
        <ul aria-label={t("previewed")} className="flex flex-col gap-2">
          {preview.data.paths.map((found) => (
            <li key={found.path} className="flex flex-wrap items-center gap-3">
              <StatusTag tone={found.matches ? "success" : "info"}>
                {found.matches ? (
                  <Check aria-hidden="true" className="size-3" />
                ) : (
                  <X aria-hidden="true" className="size-3" />
                )}
                {found.matches ? t("matches") : t("doesNotMatch")}
              </StatusTag>
              <code className="font-mono text-sm break-all">{found.path}</code>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

type Content = { name: string; description: string; expression: string };

/**
 * The form of a selector, new or not: its description and its expression, said wrong
 * where the server says so, and tried against paths before it is saved.
 */
function SelectorForm({
  selector,
  saving,
  error,
  onSave,
  saveLabel,
}: {
  /** The selector as it is, or null for one that is not there yet, which also has a name. */
  selector: SelectorOut | null;
  saving: boolean;
  error: unknown;
  onSave: (content: Content) => void;
  saveLabel: string;
}) {
  const t = useTranslations("selectors");
  const [name, setName] = useState("");
  const [description, setDescription] = useState(selector?.description ?? "");
  const [expression, setExpression] = useState(selector?.expression ?? "");
  const [previewSaid, setPreviewSaid] = useState<string | undefined>();
  const { form, tried: checked, attempt } = useAttempts(error);

  const refused = refusalsOf(error, ["name", "description", "expression"]);
  // A name another selector has: said at the name.
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const ownName =
    selector !== null
      ? undefined
      : !NAME.test(name)
        ? t("nameRule")
        : isAddressable(name)
          ? undefined
          : t("nameDots");
  const nameProblem = checked ? (ownName ?? taken ?? refused.at.name) : undefined;
  const ownExpression = expression.trim() === "" ? t("expressionNeeded") : undefined;
  const expressionProblem =
    (checked ? (ownExpression ?? refused.at.expression) : undefined) ?? previewSaid;

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    if (ownName || ownExpression) return;
    onSave({ name, description: description.trim(), expression: expression.trim() });
  }

  return (
    <div className="flex flex-col gap-8">
      <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          {selector === null ? (
            <TextField
              label={t("fields.name")}
              hint={t("hints.name")}
              required
              spellCheck={false}
              autoComplete="off"
              value={name}
              error={nameProblem}
              onChange={(event) => setName(event.target.value)}
            />
          ) : null}
          <TextField
            label={t("fields.description")}
            maxLength={255}
            value={description}
            error={checked ? refused.at.description : undefined}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <TextAreaField
          label={t("fields.expression")}
          hint={t("hints.expression")}
          required
          rows={3}
          spellCheck={false}
          className="font-mono text-sm"
          value={expression}
          error={expressionProblem}
          onChange={(event) => {
            setExpression(event.target.value);
            setPreviewSaid(undefined);
          }}
        />
        {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
        <div>
          <Button type="submit" variant="primary" busy={saving}>
            {saveLabel}
          </Button>
        </div>
      </form>
      <PreviewPanel expression={expression} onRefused={setPreviewSaid} />
    </div>
  );
}

/** A new content selector. */
export function NewSelectorScreen() {
  const t = useTranslations("selectors");
  const router = useRouter();
  const notify = useNotify();
  const create = useCreateSelector();
  const mayCreate = useMayWrite();
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: CONTENT_SELECTORS },
          { name: t("newTitle"), href: NEW_SELECTOR },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      {mayCreate ? null : <Alert tone="warning">{t("mayNotCreate")}</Alert>}
      <Panel className="p-6" hidden={!mayCreate}>
        <SelectorForm
          selector={null}
          saving={create.isPending}
          error={create.error}
          saveLabel={t("create")}
          onSave={(content) =>
            create.mutate(content, {
              onSuccess: (made) => {
                notify(t("created", { name: made.name }));
                router.push(selectorHref(made.name));
              },
            })
          }
        />
      </Panel>
    </div>
  );
}

function Edit({ selector }: { selector: SelectorOut }) {
  const t = useTranslations("selectors");
  const notify = useNotify();
  const update = useUpdateSelector(selector.name);
  return (
    <Panel className="p-6">
      <SelectorForm
        selector={selector}
        saving={update.isPending}
        error={update.error}
        saveLabel={t("save")}
        onSave={({ description, expression }) =>
          update.mutate(
            { description, expression },
            { onSuccess: () => notify(t("saved", { name: selector.name })) },
          )
        }
      />
    </Panel>
  );
}

/** A selector as it is, for whoever may read and not change it: it can still be tried. */
function Shown({ selector }: { selector: SelectorOut }) {
  const t = useTranslations("selectors");
  return (
    <Panel className="flex flex-col gap-8 p-6">
      <Facts>
        <Fact name={t("fields.description")}>{selector.description}</Fact>
        <Fact name={t("fields.expression")} mono>
          {selector.expression}
        </Fact>
      </Facts>
      <PreviewPanel expression={selector.expression} onRefused={() => undefined} />
    </Panel>
  );
}

/** One content selector: what it matches, trying it, changing it, and deleting it. */
export function SelectorScreen() {
  const t = useTranslations("selectors");
  const router = useRouter();
  const notify = useNotify();
  const where = parseSelector(usePathname());
  const mayWrite = useMayWrite();
  const remove = useDeleteSelector();
  // Once deleted, the selector is not asked for again: there is none to answer with.
  const selector = useSelector(remove.isSuccess ? null : (where?.name ?? null));
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (selector.isError) {
    return <ErrorState error={selector.error} onRetry={() => void selector.refetch()} />;
  }
  if (!selector.data || !selector.isFetchedAfterMount) return <LoadingState />;

  const found = selector.data;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: CONTENT_SELECTORS },
            { name: found.name, href: selectorHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} />
      </div>
      {mayWrite ? <Edit selector={found} /> : <Shown selector={found} />}
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
                  router.replace(CONTENT_SELECTORS);
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {t("deleteBody")}
          </ConfirmDialog>
        </Panel>
      ) : null}
    </div>
  );
}
