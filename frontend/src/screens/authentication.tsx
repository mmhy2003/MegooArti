"use client";

import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Alert, StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts } from "@/components/ui/details";
import { TextAreaField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { SourceOut } from "@/lib/api/types";
import { NEW_SOURCE, sourceHref } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  useDeleteSource,
  useEveryRole,
  useOrderSources,
  useSetDefaultRole,
  useSetLocalSignIn,
  useSetTrustedProxies,
  useSignInSettings,
  useSources,
  useTestSource,
  useUpdateSource,
} from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-3 text-lg font-semibold text-fg uppercase";
const NONE = "";

/** A source as it is sent back: what it has, with one thing changed. Its secrets stay. */
function asSent(source: SourceOut, changes: { enabled?: boolean } = {}) {
  return {
    name: source.name,
    enabled: changes.enabled ?? source.enabled,
    settings: source.settings,
    group_mapping: source.group_mapping,
  };
}

function OnOff({ on }: { on: boolean }) {
  const t = useTranslations("authentication");
  return <StatusTag tone={on ? "success" : "info"}>{on ? t("on") : t("off")}</StatusTag>;
}

/** MegooArti's own users and the sources, in the order a password is asked of them (E3). */
function Sources({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("authentication");
  const notify = useNotify();
  const settings = useSignInSettings();
  const sources = useSources();
  const local = useSetLocalSignIn();
  const update = useUpdateSource();
  const order = useOrderSources();
  const remove = useDeleteSource();
  const test = useTestSource();
  const [askingLocal, setAskingLocal] = useState(false);
  const [deleting, setDeleting] = useState<SourceOut | null>(null);
  const [tested, setTested] = useState<string | null>(null);

  const failed = settings.isError ? settings : sources.isError ? sources : null;
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  if (!settings.data || !sources.data) return <LoadingState className="p-4" />;

  const localOn = settings.data.local_sign_in.enabled;
  const listed = sources.data.items;
  const setLocal = (enabled: boolean) =>
    local.mutate(enabled, {
      onSuccess: () => notify(enabled ? t("localTurnedOn") : t("localTurnedOff")),
      onSettled: () => setAskingLocal(false),
    });
  const move = (index: number, by: -1 | 1) => {
    const ids = listed.map((source) => source.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + by, 0, moved);
    order.mutate(ids, { onSuccess: () => notify(t("moved", { name: listed[index]?.name ?? "" })) });
  };
  const turn = (source: SourceOut, enabled: boolean) =>
    update.mutate(
      { id: source.id, wanted: asSent(source, { enabled }) },
      {
        onSuccess: () =>
          notify(
            enabled ? t("turnedOn", { name: source.name }) : t("turnedOff", { name: source.name }),
          ),
      },
    );
  const failure = [local, update, order, remove].find((mutation) => mutation.isError);
  const shownTest = tested !== null && test.data && test.variables === tested ? test.data : null;

  return (
    <>
      <Table caption={t("sourcesTitle")}>
        <thead>
          <tr>
            <Th>{t("columns.name")}</Th>
            <Th>{t("columns.kind")}</Th>
            <Th className="text-right">{t("columns.users")}</Th>
            <Th>{t("columns.state")}</Th>
            {mayWrite ? <Th className="text-right">{t("columns.actions")}</Th> : null}
          </tr>
        </thead>
        <tbody>
          <tr>
            <Td className="font-medium">{t("local")}</Td>
            <Td className="text-fg-muted">{t("localKind")}</Td>
            <Td />
            <Td>
              <OnOff on={localOn} />
            </Td>
            {mayWrite ? (
              <Td className="text-right">
                <Button
                  size="sm"
                  busy={local.isPending && !askingLocal}
                  onClick={() => (localOn ? setAskingLocal(true) : setLocal(true))}
                >
                  {localOn ? t("turnOffLocal") : t("turnOnLocal")}
                </Button>
              </Td>
            ) : null}
          </tr>
          {listed.map((source, index) => (
            <tr key={source.id} className="hover:bg-raised">
              <Td className="font-medium break-all">
                <AppLink
                  href={sourceHref(source.id)}
                  className="text-ink-cyan underline-offset-4 hover:underline"
                >
                  {source.name}
                </AppLink>
              </Td>
              <Td className="font-mono text-fg-muted">{source.kind}</Td>
              <Td className="text-right font-mono">{source.users}</Td>
              <Td>
                <OnOff on={source.enabled} />
              </Td>
              {mayWrite ? (
                <Td className="text-right">
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button
                      size="sm"
                      aria-label={t("moveUp", { name: source.name })}
                      disabled={index === 0 || order.isPending}
                      onClick={() => move(index, -1)}
                    >
                      <ArrowUp aria-hidden="true" className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      aria-label={t("moveDown", { name: source.name })}
                      disabled={index === listed.length - 1 || order.isPending}
                      onClick={() => move(index, 1)}
                    >
                      <ArrowDown aria-hidden="true" className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      aria-label={t("testNamed", { name: source.name })}
                      busy={test.isPending && test.variables === source.id}
                      onClick={() => {
                        setTested(source.id);
                        test.mutate(source.id);
                      }}
                    >
                      {t("test")}
                    </Button>
                    <Button
                      size="sm"
                      aria-label={
                        source.enabled
                          ? t("turnOffNamed", { name: source.name })
                          : t("turnOnNamed", { name: source.name })
                      }
                      onClick={() => turn(source, !source.enabled)}
                    >
                      {source.enabled ? t("turnOff") : t("turnOn")}
                    </Button>
                    <Button
                      size="sm"
                      aria-label={t("deleteNamed", { name: source.name })}
                      onClick={() => {
                        remove.reset();
                        setDeleting(source);
                      }}
                    >
                      {t("delete")}
                    </Button>
                  </div>
                </Td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="flex flex-col gap-3 p-4">
        {listed.length === 0 ? <p className="text-fg-muted">{t("noSources")}</p> : null}
        <p className="text-sm text-fg-subtle">{t("order")}</p>
        {shownTest ? (
          <Alert tone={shownTest.ok ? "success" : "danger"} title={t("tested")}>
            {shownTest.message}
          </Alert>
        ) : null}
        {test.isError ? <ErrorState error={test.error} /> : null}
        {failure ? <ErrorState error={failure.error} /> : null}
      </div>
      <ConfirmDialog
        open={askingLocal}
        onOpenChange={setAskingLocal}
        title={t("askLocal")}
        confirmLabel={t("turnOffLocal")}
        busy={local.isPending}
        onConfirm={() => setLocal(false)}
      >
        {t("askLocalBody")}
      </ConfirmDialog>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("deleteAsk", { name: deleting?.name ?? "" })}
        confirmLabel={t("deleteSource")}
        mustType={deleting?.name}
        busy={remove.isPending}
        onConfirm={() => {
          if (deleting === null) return;
          remove.mutate(deleting.id, {
            onSuccess: () => notify(t("deleted", { name: deleting.name })),
            onSettled: () => setDeleting(null),
          });
        }}
      >
        {t("deleteBody", { users: deleting?.users ?? 0 })}
      </ConfirmDialog>
    </>
  );
}

/** The role every signed-in user has besides their own (spec 4.1). */
function DefaultRole({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("authentication");
  const notify = useNotify();
  const session = useSession();
  const settings = useSignInSettings();
  const mayChoose =
    mayWrite && session.data !== undefined && allows(session.data, "admin:roles:read");
  const roles = useEveryRole(mayChoose);
  const change = useSetDefaultRole();
  const [chosen, setChosen] = useState<string | null>(null);

  if (settings.isError) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  if (!settings.data) return <LoadingState className="p-4" />;
  const current = settings.data.default_role;
  if (!mayChoose) {
    return (
      <Facts>
        <Fact name={t("defaultRole")} mono>
          {current ?? t("noDefaultRole")}
        </Fact>
      </Facts>
    );
  }
  if (roles.isError) return <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />;
  if (!roles.data) return <LoadingState className="p-4" />;

  const value = chosen ?? current ?? NONE;
  function submit(event: FormEvent) {
    event.preventDefault();
    const role = value === NONE ? null : value;
    change.mutate(role, {
      onSuccess: () =>
        notify(role === null ? t("defaultRoleCleared") : t("defaultRoleSet", { role })),
    });
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <SelectField
        label={t("defaultRole")}
        value={value}
        onChange={(event) => setChosen(event.target.value)}
        choices={[
          { value: NONE, label: t("noDefaultRole") },
          ...roles.data.items.map((role) => ({ value: role.name, label: role.name })),
        ]}
      />
      {change.isError ? <ErrorState error={change.error} /> : null}
      <div>
        <Button type="submit" variant="primary" busy={change.isPending}>
          {t("save")}
        </Button>
      </div>
    </form>
  );
}

/**
 * The proxies in front of the gateway (spec 8): one an address or a network a line. Their
 * X-Forwarded-For is believed, and a header source's header is taken from them only.
 */
function TrustedProxies({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("authentication");
  const notify = useNotify();
  const settings = useSignInSettings();
  const change = useSetTrustedProxies();
  const [typed, setTyped] = useState<string | null>(null);

  if (settings.isError) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  if (!settings.data) return <LoadingState className="p-4" />;
  const kept = settings.data.trusted_proxies;
  const text = typed ?? kept.join("\n");
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  // The server says which line is wrong by its place among those sent.
  const wrong = refusalsOf(change.error, ["trusted_proxies"]);
  const at = /^trusted_proxies\.(\d+)$/.exec(
    isApiError(change.error) ? (change.error.details[0]?.field ?? "") : "",
  );
  const refusal = at ? t("proxyRefused", { line: lines[Number(at[1])] ?? "" }) : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    change.mutate(lines, {
      onSuccess: (saved) => {
        notify(t("proxiesSaved", { count: saved.trusted_proxies.length }));
        setTyped(null);
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <TextAreaField
        label={t("trustedProxies")}
        hint={t("trustedProxiesHint")}
        rows={4}
        spellCheck={false}
        className="font-mono text-sm"
        disabled={!mayWrite}
        value={text}
        error={refusal}
        onChange={(event) => setTyped(event.target.value)}
      />
      {change.isError && !refusal && wrong.elsewhere ? <ErrorState error={change.error} /> : null}
      {mayWrite ? (
        <div>
          <Button type="submit" variant="primary" busy={change.isPending}>
            {t("saveProxies")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

/** Where people sign in from, in order, and the role every signed-in user has (SEC-15, SEC-16). */
export function AuthenticationScreen() {
  const t = useTranslations("authentication");
  const session = useSession();
  const mayWrite = session.data !== undefined && allows(session.data, "admin:security:write");
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4">
          <h2 className={H2}>{t("sourcesTitle")}</h2>
          {mayWrite ? (
            <Button asChild size="sm">
              <AppLink href={NEW_SOURCE}>
                <Plus aria-hidden="true" className="size-4" />
                {t("newSource")}
              </AppLink>
            </Button>
          ) : null}
        </div>
        <Sources mayWrite={mayWrite} />
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("defaultRoleTitle")}</h2>
        <p className="mb-4 text-fg-muted">{t("defaultRoleIntro")}</p>
        <DefaultRole mayWrite={mayWrite} />
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("trustedProxiesTitle")}</h2>
        <p className="mb-4 text-fg-muted">{t("trustedProxiesIntro")}</p>
        <TrustedProxies mayWrite={mayWrite} />
      </Panel>
    </div>
  );
}
