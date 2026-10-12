"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Fact, Facts, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useEveryBlobStore, useInformation, useSetBaseUrl } from "@/lib/administration";
import type { SettingsOut } from "@/lib/api/types";
import { useAttempts } from "@/lib/focus";
import { BLOB_STORES } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { useSettings } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { BlobStoreTable } from "@/screens/blob-stores";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

/**
 * Whether what was typed is an address the server takes for its own: http or https, no
 * more than a path, and nobody's name or password, which every address the server
 * gives out would then carry (H4).
 */
function isBaseUrl(typed: string): boolean {
  try {
    const url = new URL(typed);
    const web = url.protocol === "http:" || url.protocol === "https:";
    // The part between the slashes and the path: "user:password@host", or "@host".
    const named = (typed.split("/")[2] ?? "").includes("@");
    return web && url.hostname !== "" && !named && !url.search && !url.hash;
  } catch {
    return false;
  }
}

/** What is running (R11, R12). */
function Running() {
  const t = useTranslations("system");
  const information = useInformation();
  if (information.isError) {
    return <ErrorState error={information.error} onRetry={() => void information.refetch()} />;
  }
  if (!information.data) return <LoadingState className="p-4" />;
  const { version, schema, runtime, database } = information.data;
  return (
    <Facts>
      <Fact name={t("facts.version")} copy={version} mono>
        {version}
      </Fact>
      <Fact name={t("facts.schema")}>
        <span className="flex flex-wrap items-center gap-2">
          <code className="font-mono text-xs">{schema.revision ?? t("neverMigrated")}</code>
          {schema.current ? (
            <StatusTag tone="success">{t("schemaCurrent")}</StatusTag>
          ) : (
            <StatusTag tone="danger">{t("schemaOther", { expected: schema.expected })}</StatusTag>
          )}
        </span>
      </Fact>
      <Fact name={t("facts.started")}>
        <Time value={runtime.started_at} />
      </Fact>
      <Fact name={t("facts.python")} mono>
        {runtime.python}
      </Fact>
      <Fact name={t("facts.platform")} mono>
        {runtime.platform}
      </Fact>
      <Fact name={t("facts.database")} mono>
        {database.version}
      </Fact>
    </Facts>
  );
}

/** The address the server gives out as its own. Empty, it is the address of each request. */
function BaseUrl({ settings, mayWrite }: { settings: SettingsOut; mayWrite: boolean }) {
  const t = useTranslations("system");
  const notify = useNotify();
  const change = useSetBaseUrl();
  const [typed, setTyped] = useState(settings.base_url ?? "");
  const { form, tried, attempt } = useAttempts(change.error);
  const refused = refusalsOf(change.error, ["base_url"]);
  const wanted = typed.trim();
  const own = wanted === "" || isBaseUrl(wanted) ? undefined : t("baseUrlRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    change.reset();
    if (own) return;
    change.mutate(wanted === "" ? null : wanted, {
      onSuccess: (saved) => {
        // As the server keeps it: without a slash at its end.
        setTyped(saved.base_url ?? "");
        notify(saved.base_url === null ? t("baseUrlCleared") : t("baseUrlSaved"));
      },
    });
  }

  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <TextField
        label={t("fields.baseUrl")}
        hint={t("hints.baseUrl")}
        type="url"
        spellCheck={false}
        autoComplete="off"
        disabled={!mayWrite}
        value={typed}
        error={tried ? (own ?? refused.at.base_url) : undefined}
        onChange={(event) => setTyped(event.target.value)}
      />
      {change.isError && refused.elsewhere ? <ErrorState error={change.error} /> : null}
      {mayWrite ? (
        <div>
          <Button type="submit" variant="primary" busy={change.isPending}>
            {t("saveBaseUrl")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

/** The installation itself (R11): what runs, the address it gives out, and its blob stores. */
export function SystemScreen() {
  const t = useTranslations("system");
  const session = useSession();
  const may = (permission: string) =>
    session.data !== undefined && allows(session.data, permission);
  const settings = useSettings();
  const storesReadable = may("admin:blobstores:read");
  const stores = useEveryBlobStore(storesReadable);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="p-6">
        <h2 className={H2}>{t("runningTitle")}</h2>
        <Running />
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("baseUrlTitle")}</h2>
        {settings.isError ? (
          <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
        ) : !settings.data || !settings.isFetchedAfterMount ? (
          <LoadingState className="p-4" />
        ) : (
          <BaseUrl settings={settings.data} mayWrite={may("admin:settings:write")} />
        )}
      </Panel>
      {storesReadable ? (
        <Panel>
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-6">
            <h2 className="text-lg font-semibold text-fg uppercase">{t("storesTitle")}</h2>
            <AppLink
              href={BLOB_STORES}
              className="text-sm text-ink-cyan underline-offset-4 hover:underline"
            >
              {t("toStores")}
            </AppLink>
          </div>
          {stores.isError ? (
            <ErrorState
              error={stores.error}
              onRetry={() => void stores.refetch()}
              className="m-6"
            />
          ) : !stores.data ? (
            <LoadingState />
          ) : (
            <BlobStoreTable caption={t("storesTitle")} stores={stores.data} />
          )}
        </Panel>
      ) : null}
    </div>
  );
}
