"use client";

import type { Route } from "next";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { GroupMapping, toGrants, toMapping, type Grant } from "@/components/group-mapping";
import { isKindName, SOURCE_KINDS, type KindName, type Values } from "@/components/source-fields";
import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { Fact, Facts } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { ChoiceGroup } from "@/components/ui/inputs";
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

/**
 * A source's settings, by its kind (OIDC, spec 5; LDAP, spec 7), with its name and the
 * roles its groups give. Made off: it is tested, then turned on, on the list.
 */
function SourceForm({
  kind,
  source,
  mayWrite,
}: {
  kind: KindName;
  source: SourceOut | null;
  mayWrite: boolean;
}) {
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
  const fields = SOURCE_KINDS[kind];
  const [name, setName] = useState(source?.name ?? "");
  const [values, setValues] = useState<Values>(() => fields.initial(source));
  const [grants, setGrants] = useState<Grant[]>(() => toGrants(source?.group_mapping ?? []));
  const { form, tried, attempt } = useAttempts(saving.error);
  const refused = refusalsOf(saving.error, [
    "name",
    "group_mapping",
    ...fields.fields.map((field) => `settings.${field}`),
  ]);
  const own = {
    ...fields.own(values, t),
    name: NAME.test(name) ? undefined : t("nameRule"),
    // A row with a group and no role, or a role and no group, would be dropped unsaid.
    mapping: grants.some(({ group, role }) => (group.trim() === "") !== (role === ""))
      ? t("rowIncomplete")
      : undefined,
  };
  const at = (field: string, mine?: string) =>
    tried ? (mine ?? refused.at[field === "name" ? "name" : `settings.${field}`]) : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    saving.reset();
    if (Object.values(own).some(Boolean)) return;
    const sent = {
      name,
      enabled: source?.enabled ?? false,
      settings: fields.sent(values),
      group_mapping: toMapping(grants),
    };
    if (source === null) {
      create.mutate(
        { ...sent, kind },
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
            setValues({ ...values, [fields.secret]: "" });
          },
        },
      );
    }
  }

  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-6 border-0 p-0">
        <Panel className="flex flex-col gap-5 p-6">
          <h2 className={H2}>{kind === "ldap" ? t("ldap.title") : t("providerTitle")}</h2>
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            autoComplete="off"
            value={name}
            error={at("name", own.name)}
            onChange={(event) => setName(event.target.value)}
          />
          <fields.Fields
            values={values}
            change={(changed) => setValues({ ...values, ...changed })}
            at={at}
            own={own}
            hasSecret={source?.secrets.includes(fields.secret) ?? false}
          />
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

/** A new source: its kind chosen first, then its form. */
export function NewSourceScreen() {
  const t = useTranslations("source");
  const session = useSession();
  const [kind, setKind] = useState<KindName>("oidc");
  if (!session.data) return <LoadingState />;
  if (!allows(session.data, "admin:security:write")) return <NothingHere />;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Path name={t("newTitle")} href={NEW_SOURCE} />
        <PageHeader title={t("newTitle")} intro={t("newIntro")} />
      </div>
      <Panel className="p-6">
        <ChoiceGroup
          legend={t("kind")}
          value={kind}
          onChange={(chosen) => setKind(chosen as KindName)}
          options={[
            { value: "oidc", label: t("kinds.oidc"), hint: t("kinds.oidcHint") },
            { value: "ldap", label: t("kinds.ldap"), hint: t("kinds.ldapHint") },
          ]}
        />
      </Panel>
      {/* Another kind is another form, from the start. */}
      <SourceForm key={kind} kind={kind} source={null} mayWrite />
    </div>
  );
}

/** One source: its settings, and for OIDC the address to register at the provider. */
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
      {isKindName(found.kind) ? (
        <SourceForm kind={found.kind} source={found} mayWrite={mayWrite} />
      ) : (
        <Alert tone="info">{t("noForm", { kind: found.kind })}</Alert>
      )}
    </div>
  );
}
