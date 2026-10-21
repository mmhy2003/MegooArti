"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AccountNav } from "@/components/account-nav";
import { PermissionRows, patternsAreValid } from "@/components/permission-rows";
import { TokenList } from "@/components/token-list";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { ChoiceGroup, SelectField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import type { TokenCreated } from "@/lib/api/types";
import { useRepositories } from "@/lib/content";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import { endOfDay } from "@/lib/format";
import { ACCOUNT_TOKENS, pageHref, pageOf } from "@/lib/paths";
import { READ_ONLY } from "@/lib/patterns";
import { refusalsOf } from "@/lib/refusals";
import { useSelectorNames } from "@/lib/selectors";
import { AT_ONCE, useCreateToken, useMyTokens, useRevokeToken } from "@/lib/security";

const DAY = 24 * 3600 * 1000;
// How long a token lasts: never, a number of days, or until a day that is chosen.
const LASTS = ["never", "30", "90", "365", "date"] as const;
type Lasts = (typeof LASTS)[number];
const LIMITS = ["everything", "read", "custom"] as const;
type Limit = (typeof LIMITS)[number];

/**
 * The moment a token ends, as the API takes it: null for one that does not end, and
 * undefined where a day was to be chosen and what is there is no day.
 */
function expiryOf(lasts: Lasts, day: string): string | null | undefined {
  if (lasts === "never") return null;
  if (lasts === "date") return endOfDay(day) ?? undefined;
  return new Date(Date.now() + Number(lasts) * DAY).toISOString();
}

/**
 * A token that was just made (A5). Its secret is here and nowhere else, and only
 * until this is closed or the page is left.
 */
function Made({ token, onDone }: { token: TokenCreated; onDone: () => void }) {
  const t = useTranslations("tokens");
  const heading = useRef<HTMLHeadingElement>(null);
  // The form that made it is gone: the keyboard, and a screen reader, come here.
  useEffect(() => heading.current?.focus(), []);
  return (
    <Panel role="region" aria-labelledby="made-token" className="mb-6 border-ok p-6">
      <h2
        id="made-token"
        ref={heading}
        tabIndex={-1}
        className="mb-2 text-lg font-semibold text-fg outline-none"
      >
        {t("madeTitle", { name: token.name })}
      </h2>
      <Alert tone="warning" className="mb-4">
        {t("madeOnce")}
      </Alert>
      <div className="flex items-start gap-2 rounded-sm border border-line bg-field p-3">
        <code className="min-w-0 flex-1 font-mono text-sm break-all text-fg">{token.token}</code>
        <CopyButton text={token.token} what={t("theToken")} className="-my-1" />
      </div>
      <p className="mt-3 text-sm text-fg-muted">{t("madeUse")}</p>
      <Button className="mt-4" onClick={onDone}>
        {t("madeDone")}
      </Button>
    </Panel>
  );
}

function Create({ onCreated }: { onCreated: (token: TokenCreated) => void }) {
  const t = useTranslations("tokens");
  const create = useCreateToken();
  const repositories = useRepositories();
  const selectors = useSelectorNames();
  const [name, setName] = useState("");
  const [lasts, setLasts] = useState<Lasts>("90");
  const [day, setDay] = useState("");
  const [limit, setLimit] = useState<Limit>("everything");
  const [custom, setCustom] = useState<string[]>([]);
  const { form, tried: checked, attempt } = useAttempts(create.error);

  const until = expiryOf(lasts, day);
  const refused = refusalsOf(create.error, ["name", "expires_at", "scopes"]);
  // A name that another of one's tokens has: said at the name.
  const taken =
    isApiError(create.error) && create.error.code === "conflict" ? create.error.message : null;
  const problems = {
    name: !checked ? undefined : name.trim() === "" ? t("nameNeeded") : (taken ?? refused.at.name),
    day:
      checked && until === undefined
        ? t("dayNeeded")
        : lasts === "date"
          ? refused.at.expires_at
          : undefined,
    custom:
      checked && limit === "custom" && custom.length === 0 ? t("customNeeded") : refused.at.scopes,
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    create.reset();
    const scopes = limit === "everything" ? null : limit === "read" ? [...READ_ONLY] : custom;
    if (name.trim() === "" || until === undefined) return;
    if (scopes !== null && (scopes.length === 0 || !patternsAreValid(scopes))) return;
    create.mutate({ name: name.trim(), expires_at: until, scopes }, { onSuccess: onCreated });
  }

  return (
    <Panel className="mb-6 p-6">
      <h2 className="mb-4 text-lg font-semibold text-fg uppercase">{t("createTitle")}</h2>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            maxLength={100}
            value={name}
            error={problems.name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className="flex flex-col gap-3">
            <SelectField
              label={t("fields.lasts")}
              value={lasts}
              onChange={(event) => setLasts(event.target.value as Lasts)}
              choices={LASTS.map((value) => ({ value, label: t(`lasts.${value}`) }))}
            />
            {lasts === "date" ? (
              <TextField
                label={t("fields.day")}
                type="date"
                // A year of four digits: a field without this takes one of five.
                max="9999-12-31"
                required
                value={day}
                error={problems.day}
                onChange={(event) => setDay(event.target.value)}
              />
            ) : null}
          </div>
        </div>
        <ChoiceGroup
          legend={t("fields.limit")}
          value={limit}
          onChange={(value) => setLimit(value as Limit)}
          options={LIMITS.map((value) => ({
            value,
            label: t(`limits.${value}`),
            hint: t(`limitHints.${value}`),
          }))}
        />
        {limit === "custom" ? (
          <>
            <PermissionRows
              legend={t("fields.custom")}
              initial={custom}
              onChange={setCustom}
              repositories={repositories.data?.items ?? []}
              selectors={selectors}
              checked={checked}
            />
            {problems.custom ? <Alert tone="danger">{problems.custom}</Alert> : null}
          </>
        ) : null}
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

/** A person's own API tokens (A4, A5): those there are, a new one, and revoking one. */
export function TokensScreen() {
  const t = useTranslations("tokens");
  const notify = useNotify();
  const page = pageOf(useSearchParams());
  const tokens = useMyTokens(page);
  const revoke = useRevokeToken();
  const [made, setMade] = useState<TokenCreated | null>(null);
  const pages = tokens.data === undefined ? undefined : Math.ceil(tokens.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(ACCOUNT_TOKENS, target);
  // The heading of the list takes the keyboard when a page of it is turned, and when
  // the panel of a token that was just made is closed.
  const listed = usePageFocus<HTMLHeadingElement>(page, tokens.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);

  return (
    <div className="mx-auto max-w-5xl">
      <AccountNav />
      <PageHeader title={t("title")} intro={t("intro")} />
      {made ? (
        <Made
          token={made}
          onDone={() => {
            // The panel that had the keyboard goes: it is put at the tokens, where the
            // new one now is.
            listed.current?.focus();
            setMade(null);
          }}
        />
      ) : (
        <Create onCreated={setMade} />
      )}
      <Panel>
        <h2
          ref={listed}
          tabIndex={-1}
          className="px-4 pt-4 text-lg font-semibold text-fg uppercase outline-none"
        >
          {t("listTitle")}
        </h2>
        {tokens.isError ? (
          <ErrorState error={tokens.error} onRetry={() => void tokens.refetch()} className="m-4" />
        ) : !tokens.data || beyond ? (
          <LoadingState />
        ) : (
          <>
            <TokenList
              caption={t("listTitle")}
              tokens={tokens.data.items}
              empty={t("none")}
              onRevoke={async (token) => {
                await revoke.mutateAsync(token.id);
                notify(t("revoked", { name: token.name }));
              }}
            />
            <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
          </>
        )}
      </Panel>
    </div>
  );
}
