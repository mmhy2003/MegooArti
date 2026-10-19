"use client";

import type { Route } from "next";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { GroupMapping, toGrants, toMapping, type Grant } from "@/components/group-mapping";
import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { Fact, Facts } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import type { SourceOut } from "@/lib/api/types";
import { useAttempts } from "@/lib/focus";
import { AUTHENTICATION, NEW_SOURCE, parseSource, sourceHref } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { useCreateSource, useEveryRole, useSource, useUpdateSource } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
// The server's rule for a source's name, said before the request is made.
const NAME = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/;
const CLAIMS = ["username_claim", "name_claim", "email_claim", "groups_claim"] as const;
const DEFAULT_CLAIMS: Record<(typeof CLAIMS)[number], string> = {
  username_claim: "preferred_username",
  name_claim: "name",
  email_claim: "email",
  groups_claim: "groups",
};
const FIELDS = [
  "name",
  "group_mapping",
  "settings.issuer",
  "settings.client_id",
  "settings.client_secret",
  "settings.scopes",
  ...CLAIMS.map((claim) => `settings.${claim}`),
];

type OidcSettings = {
  issuer: string;
  client_id: string;
  client_secret: string;
  scopes: string;
  require_verified_email: boolean;
} & Record<(typeof CLAIMS)[number], string>;

function fromSource(source: SourceOut | null): OidcSettings {
  const kept = (source?.settings ?? {}) as Record<string, unknown>;
  const text = (name: string, otherwise = "") =>
    typeof kept[name] === "string" ? (kept[name] as string) : otherwise;
  return {
    issuer: text("issuer"),
    client_id: text("client_id"),
    client_secret: "",
    scopes: Array.isArray(kept.scopes)
      ? (kept.scopes as string[]).join(" ")
      : "openid profile email",
    require_verified_email: kept.require_verified_email === true,
    ...Object.fromEntries(CLAIMS.map((claim) => [claim, text(claim, DEFAULT_CLAIMS[claim])])),
  } as OidcSettings;
}

/**
 * An OIDC source's settings (spec 5): the provider, this server's client there, and the
 * claims that say who someone is. The secret is written, never read back: left empty, the
 * stored one is kept.
 */
function OidcForm({ source, mayWrite }: { source: SourceOut | null; mayWrite: boolean }) {
  const t = useTranslations("source");
  const notify = useNotify();
  const router = useRouter();
  const create = useCreateSource();
  const update = useUpdateSource();
  const saving = source === null ? create : update;
  const session = useSession();
  const roles = useEveryRole(
    session.data !== undefined && allows(session.data, "admin:roles:read"),
  );
  const [name, setName] = useState(source?.name ?? "");
  const [settings, setSettings] = useState<OidcSettings>(() => fromSource(source));
  const [grants, setGrants] = useState<Grant[]>(() => toGrants(source?.group_mapping ?? []));
  const { form, tried, attempt } = useAttempts(saving.error);
  const refused = refusalsOf(saving.error, FIELDS);
  const hasSecret = source?.secrets.includes("client_secret") ?? false;
  const own = {
    name: NAME.test(name) ? undefined : t("nameRule"),
    issuer: /^https?:\/\/[^/]+/.test(settings.issuer.trim()) ? undefined : t("issuerRule"),
    client_id: settings.client_id.trim() === "" ? t("clientIdNeeded") : undefined,
    // A row with a group and no role, or a role and no group, would be dropped unsaid.
    mapping: grants.some(({ group, role }) => (group.trim() === "") !== (role === ""))
      ? t("rowIncomplete")
      : undefined,
  };
  const at = (field: string, mine?: string) =>
    tried ? (mine ?? refused.at[field === "name" ? "name" : `settings.${field}`]) : undefined;
  const change = (changed: Partial<OidcSettings>) => setSettings({ ...settings, ...changed });

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    saving.reset();
    if (Object.values(own).some(Boolean)) return;
    const sent = {
      name,
      enabled: source?.enabled ?? false,
      settings: {
        issuer: settings.issuer.trim(),
        client_id: settings.client_id.trim(),
        scopes: settings.scopes.split(/\s+/).filter(Boolean),
        require_verified_email: settings.require_verified_email,
        ...Object.fromEntries(CLAIMS.map((claim) => [claim, settings[claim].trim()])),
        // Left out, the stored secret is kept.
        ...(settings.client_secret === "" ? {} : { client_secret: settings.client_secret }),
      },
      group_mapping: toMapping(grants),
    };
    if (source === null) {
      create.mutate(
        { ...sent, kind: "oidc" },
        {
          onSuccess: (made) => {
            notify(t("created", { name: made.name }));
            router.replace(sourceHref(made.id));
          },
        },
      );
    } else {
      update.mutate(
        { id: source.id, wanted: sent },
        {
          onSuccess: () => {
            notify(t("saved", { name }));
            setSettings({ ...settings, client_secret: "" });
          },
        },
      );
    }
  }

  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-6 border-0 p-0">
        <Panel className="flex flex-col gap-5 p-6">
          <h2 className={H2}>{t("providerTitle")}</h2>
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            autoComplete="off"
            value={name}
            error={at("name", own.name)}
            onChange={(event) => setName(event.target.value)}
          />
          <TextField
            label={t("fields.issuer")}
            hint={t("hints.issuer")}
            required
            spellCheck={false}
            autoComplete="off"
            value={settings.issuer}
            error={at("issuer", own.issuer)}
            onChange={(event) => change({ issuer: event.target.value })}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label={t("fields.clientId")}
              required
              spellCheck={false}
              autoComplete="off"
              value={settings.client_id}
              error={at("client_id", own.client_id)}
              onChange={(event) => change({ client_id: event.target.value })}
            />
            <TextField
              label={t("fields.clientSecret")}
              hint={hasSecret ? t("hints.secretKept") : t("hints.secret")}
              type="password"
              autoComplete="new-password"
              value={settings.client_secret}
              error={at("client_secret")}
              onChange={(event) => change({ client_secret: event.target.value })}
            />
          </div>
          <TextField
            label={t("fields.scopes")}
            hint={t("hints.scopes")}
            spellCheck={false}
            autoComplete="off"
            value={settings.scopes}
            error={at("scopes")}
            onChange={(event) => change({ scopes: event.target.value })}
          />
          <CheckboxField
            label={t("fields.verifiedEmail")}
            hint={t("hints.verifiedEmail")}
            checked={settings.require_verified_email}
            onChange={(event) => change({ require_verified_email: event.target.checked })}
          />
        </Panel>
        <Panel className="flex flex-col gap-5 p-6">
          <h2 className={H2}>{t("claimsTitle")}</h2>
          <p className="text-fg-muted">{t("claimsIntro")}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {CLAIMS.map((claim) => (
              <TextField
                key={claim}
                label={t(`fields.${claim}`)}
                spellCheck={false}
                autoComplete="off"
                value={settings[claim]}
                error={at(claim)}
                onChange={(event) => change({ [claim]: event.target.value })}
              />
            ))}
          </div>
        </Panel>
        <Panel className="p-6">
          <GroupMapping
            grants={grants}
            roles={(roles.data?.items ?? []).map((role) => role.name)}
            onChange={setGrants}
            error={tried ? (own.mapping ?? refused.at.group_mapping) : undefined}
          />
        </Panel>
      </fieldset>
      {saving.isError && refused.elsewhere ? <ErrorState error={saving.error} /> : null}
      {mayWrite ? (
        <div>
          <Button type="submit" variant="primary" busy={saving.isPending}>
            {source === null ? t("create") : t("save")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

function Path({ name, href }: { name: string; href: Route }) {
  const t = useTranslations("source");
  return (
    <Breadcrumbs
      label={t("path")}
      crumbs={[
        { name: t("authentication"), href: AUTHENTICATION },
        { name, href },
      ]}
    />
  );
}

/** A new OIDC source (spec 5), made off: it is tested, then turned on, on the list. */
export function NewSourceScreen() {
  const t = useTranslations("source");
  const session = useSession();
  if (!session.data) return <LoadingState />;
  if (!allows(session.data, "admin:security:write")) return <NothingHere />;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Path name={t("newTitle")} href={NEW_SOURCE} />
        <PageHeader title={t("newTitle")} intro={t("newIntro")} />
      </div>
      <OidcForm source={null} mayWrite />
    </div>
  );
}

/** One source: its settings, and the address to register at the provider. */
export function SourceScreen() {
  const t = useTranslations("source");
  const session = useSession();
  const where = parseSource(usePathname());
  const source = useSource(where?.id ?? null);

  if (where === null) return <NothingHere />;
  if (source.isError)
    return <ErrorState error={source.error} onRetry={() => void source.refetch()} />;
  // Opened on what the server holds now, not on what was fetched before (A23).
  if (!source.data || !source.isFetchedAfterMount || !session.data) return <LoadingState />;
  const found = source.data;
  const mayWrite = allows(session.data, "admin:security:write");
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Path name={found.name} href={sourceHref(found.id)} />
        <PageHeader named title={found.name} intro={t("intro")} />
      </div>
      {found.redirect_uri ? (
        <Panel className="p-6">
          <Facts>
            <Fact name={t("redirectUri")} copy={found.redirect_uri} mono>
              {found.redirect_uri}
            </Fact>
          </Facts>
          <p className="mt-3 text-sm text-fg-subtle">{t("redirectUriHint")}</p>
        </Panel>
      ) : null}
      {found.kind === "oidc" ? (
        <OidcForm source={found} mayWrite={mayWrite} />
      ) : (
        <Alert tone="info">{t("noForm", { kind: found.kind })}</Alert>
      )}
    </div>
  );
}
