"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ChoiceGroup, SelectField } from "@/components/ui/inputs";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import type { Consent } from "@/lib/api/types";
import { leaveFor } from "@/lib/leave";
import { useApprove, useConsentRequest, useRefuse } from "@/lib/security";

const ACCESS = ["read", "all"] as const;
const LASTS = ["1d", "30d", "90d", "forever"] as const;

/**
 * The consent page (MCP spec 7.3): an application signing in with OAuth asks to act as
 * the person signed in, and they choose what it may do, and for how long, or refuse.
 * The application's name is its own words, and is shown as such.
 */
export function ConnectScreen() {
  const t = useTranslations("connect");
  const request = useSearchParams().get("request") ?? "";
  const asked = useConsentRequest(request);
  const approve = useApprove();
  const refuse = useRefuse();
  const [access, setAccess] = useState<Consent["access"]>("read");
  const [lasts, setLasts] = useState<Consent["lasts"]>("30d");
  const busy = approve.isPending || refuse.isPending;

  function allow(event: FormEvent) {
    event.preventDefault();
    approve.mutate({ request, access, lasts }, { onSuccess: (sent) => leaveFor(sent.redirect) });
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={t("title")} />
      {request === "" ? (
        <Alert tone="danger">{t("nothingAsked")}</Alert>
      ) : asked.isError ? (
        <ErrorState error={asked.error} />
      ) : !asked.data ? (
        <LoadingState />
      ) : (
        <Panel className="p-6">
          <p className="mb-2 text-fg">
            {t.rich("asks", {
              name: asked.data.client,
              app: (chunks) => <strong className="break-all">{chunks}</strong>,
            })}
          </p>
          <p className="mb-6 text-sm text-fg-muted">
            {t("itsWords", { host: asked.data.redirect_host })}
          </p>
          <form onSubmit={allow} className="flex flex-col gap-5">
            <ChoiceGroup
              legend={t("fields.access")}
              value={access}
              onChange={(value) => setAccess(value as Consent["access"])}
              options={ACCESS.map((value) => ({
                value,
                label: t(`access.${value}`),
                hint: t(`accessHints.${value}`),
              }))}
            />
            <SelectField
              label={t("fields.lasts")}
              value={lasts}
              onChange={(event) => setLasts(event.target.value as Consent["lasts"])}
              choices={LASTS.map((value) => ({ value, label: t(`lasts.${value}`) }))}
            />
            {approve.isError ? <ErrorState error={approve.error} /> : null}
            {refuse.isError ? <ErrorState error={refuse.error} /> : null}
            <div className="flex flex-wrap gap-3">
              <Button type="submit" variant="primary" busy={approve.isPending} disabled={busy}>
                {t("allow")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                busy={refuse.isPending}
                disabled={busy}
                onClick={() =>
                  refuse.mutate(request, { onSuccess: (sent) => leaveFor(sent.redirect) })
                }
              >
                {t("refuse")}
              </Button>
            </div>
          </form>
        </Panel>
      )}
    </div>
  );
}
