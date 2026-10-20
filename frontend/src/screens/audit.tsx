"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Pager, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import {
  AT_ONCE,
  auditExportHref,
  useAuditRecords,
  useAuditRetention,
  useSetAuditRetention,
  type AuditFilters,
} from "@/lib/administration";
import type { AuditRecordOut } from "@/lib/api/types";
import { auditHref, pageOf } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
/** The kinds of event a person filters by: what each record's event starts with. */
const KINDS = [
  "sign_in",
  "session",
  "user",
  "role",
  "token",
  "connected_app",
  "oauth_client",
  "source",
  "setting",
  "certificate",
  "repository",
  "signing_key",
  "blob_store",
] as const;
const FILTERS = ["event", "actor", "target", "since", "until"] as const;

function filtersOf(search: { get(name: string): string | null }): AuditFilters {
  return Object.fromEntries(
    FILTERS.map((name) => [name, search.get(name) ?? ""]).filter(([, value]) => value !== ""),
  ) as AuditFilters;
}

/** A value as a record holds it, in a line: a name as it is, anything else as JSON. */
function shown(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** What one record changed: each field, before and after. */
function Changes({ entry }: { entry: AuditRecordOut }) {
  const t = useTranslations("audit");
  const changed = Object.entries(entry.changes ?? {}) as [
    string,
    { before?: unknown; after?: unknown },
  ][];
  if (changed.length === 0) return <span className="text-fg-subtle">{t("nothing")}</span>;
  return (
    <details>
      <summary className="cursor-pointer text-neon-cyan">
        {t("changed", { count: changed.length })}
      </summary>
      <dl className="mt-2 flex flex-col gap-1 font-mono text-xs">
        {changed.map(([field, { before, after }]) => (
          <div key={field} className="break-all">
            <dt className="inline text-fg-muted">{t("field", { field })}</dt>
            <dd className="inline">
              {t("fromTo", { before: shown(before), after: shown(after) })}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/** Which records: of a kind of event, by whom, about what, and when. */
function Filters({ asked }: { asked: AuditFilters }) {
  const t = useTranslations("audit");
  const router = useRouter();
  const [typed, setTyped] = useState<AuditFilters>(asked);

  function submit(event: FormEvent) {
    event.preventDefault();
    router.push(auditHref(typed, 1));
  }

  const field = (name: (typeof FILTERS)[number]) => ({
    value: typed[name] ?? "",
    onChange: (event: { target: { value: string } }) =>
      setTyped({ ...typed, [name]: event.target.value }),
  });

  return (
    <form
      onSubmit={submit}
      className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6 lg:items-end"
      role="search"
      aria-label={t("filters")}
      noValidate
    >
      <SelectField
        label={t("fields.event")}
        choices={[
          { value: "", label: t("everyEvent") },
          ...KINDS.map((kind) => ({ value: kind, label: t(`kinds.${kind}`) })),
        ]}
        {...field("event")}
      />
      <TextField label={t("fields.actor")} spellCheck={false} {...field("actor")} />
      <TextField label={t("fields.target")} spellCheck={false} {...field("target")} />
      <TextField label={t("fields.since")} type="date" {...field("since")} />
      <TextField label={t("fields.until")} type="date" {...field("until")} />
      <div>
        <Button type="submit" variant="primary">
          {t("apply")}
        </Button>
      </div>
    </form>
  );
}

/** How many days records are kept: changed by whoever may, shown to whoever may read them. */
function Retention({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("audit");
  const notify = useNotify();
  const kept = useAuditRetention();
  const change = useSetAuditRetention();
  const [typed, setTyped] = useState<string | null>(null);
  const refused = refusalsOf(change.error, ["audit_retention_days"]);

  if (kept.isError) return <ErrorState error={kept.error} onRetry={() => void kept.refetch()} />;
  if (!kept.data) return <LoadingState className="p-4" />;
  const text = typed ?? String(kept.data.audit_retention_days);
  const days = Number(text);
  const wrong = /^[0-9]{1,5}$/.test(text) && days >= 1 && days <= 36500 ? undefined : t("daysRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (wrong) return;
    change.mutate(days, {
      onSuccess: (saved) => {
        notify(t("retentionSaved", { count: saved.audit_retention_days }));
        setTyped(null);
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-4" noValidate>
      <TextField
        label={t("fields.days")}
        hint={t("hints.days")}
        className="w-48"
        inputMode="numeric"
        disabled={!mayWrite}
        value={text}
        error={wrong ?? refused.at.audit_retention_days}
        onChange={(event) => setTyped(event.target.value)}
      />
      {mayWrite ? (
        <Button type="submit" busy={change.isPending}>
          {t("saveRetention")}
        </Button>
      ) : null}
      {change.isError && refused.elsewhere ? <ErrorState error={change.error} /> : null}
    </form>
  );
}

/** The audit log (spec 9): who changed what, and every sign-in, newest first. */
export function AuditScreen() {
  const t = useTranslations("audit");
  const session = useSession();
  const search = useSearchParams();
  const page = pageOf(search);
  const asked = filtersOf(search);
  const listed = useAuditRecords(page, asked);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:audit:write");
  const pages = listed.data === undefined ? undefined : Math.ceil(listed.data.total / AT_ONCE);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="p-6">
        {/* Keyed by what was asked: a link to other filters starts the form anew. */}
        <Filters key={search.toString()} asked={asked} />
        <div className="mt-4 flex flex-wrap gap-3">
          {(["jsonl", "csv"] as const).map((format) => (
            <Button key={format} asChild size="sm">
              <a href={auditExportHref(format, asked)} download>
                <Download aria-hidden="true" className="size-4" />
                {t(`export.${format}`)}
              </a>
            </Button>
          ))}
        </div>
      </Panel>
      <Panel>
        {listed.isError ? (
          <ErrorState error={listed.error} onRetry={() => void listed.refetch()} className="m-4" />
        ) : !listed.data ? (
          <LoadingState />
        ) : listed.data.items.length === 0 ? (
          <p className="p-6 text-fg-muted">{t("none")}</p>
        ) : (
          <>
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.at")}</Th>
                  <Th>{t("columns.actor")}</Th>
                  <Th>{t("columns.event")}</Th>
                  <Th>{t("columns.target")}</Th>
                  <Th>{t("columns.address")}</Th>
                  <Th>{t("columns.changes")}</Th>
                </tr>
              </thead>
              <tbody>
                {listed.data.items.map((entry) => (
                  <tr key={entry.id} className="align-top hover:bg-raised">
                    <Td className="whitespace-nowrap">
                      <Time value={entry.at} />
                    </Td>
                    <Td>
                      <span className="block">{entry.actor ?? t("nobody")}</span>
                      {entry.method ? (
                        <span className="text-xs text-fg-subtle">
                          {t("method", { method: entry.method })}
                        </span>
                      ) : null}
                    </Td>
                    <Td className="font-mono text-xs">{entry.event}</Td>
                    <Td className="break-all">
                      {entry.target_name === null ? (
                        "—"
                      ) : (
                        <>
                          <span className="block text-xs text-fg-subtle">{entry.target_kind}</span>
                          {entry.target_name}
                        </>
                      )}
                    </Td>
                    <Td className="font-mono text-xs">{entry.address ?? "—"}</Td>
                    <Td className="min-w-48">
                      <Changes entry={entry} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pager page={page} pages={pages ?? 1} hrefFor={(target) => auditHref(asked, target)} />
          </>
        )}
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("retentionTitle")}</h2>
        <p className="mb-4 text-fg-muted">{t("retentionIntro")}</p>
        <Retention mayWrite={mayWrite} />
      </Panel>
    </div>
  );
}
