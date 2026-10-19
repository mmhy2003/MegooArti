"use client";

import { Download, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager, Time } from "@/components/ui/details";
import { TextAreaField, TextField } from "@/components/ui/field";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import {
  AT_ONCE,
  useAddCertificate,
  useCertificates,
  useDeleteCertificate,
  useFetchCertificates,
} from "@/lib/administration";
import type { CertificateOut, CertificateView } from "@/lib/api/types";
import { formatFingerprint, shortFingerprint } from "@/lib/format";
import { CERTIFICATES, pageHref, pageOf } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
const PORT = /^[0-9]{1,5}$/;

function expired(certificate: { not_after: string }): boolean {
  return new Date(certificate.not_after).getTime() < Date.now();
}

/** A certificate as it is checked before it is trusted: who it is, who vouches for it, its fingerprint. */
function Described({ certificate }: { certificate: CertificateView }) {
  const t = useTranslations("certificates");
  return (
    <Facts>
      <Fact name={t("columns.subject")} mono>
        {certificate.subject}
      </Fact>
      <Fact name={t("columns.issuer")} mono>
        {certificate.issuer}
      </Fact>
      <Fact name={t("fingerprint")} copy={formatFingerprint(certificate.fingerprint)} mono>
        {formatFingerprint(certificate.fingerprint)}
      </Fact>
      <Fact name={t("columns.expires")}>
        <Time value={certificate.not_after} />
        {expired(certificate) ? (
          <StatusTag tone="danger" className="ml-2">
            {t("expired")}
          </StatusTag>
        ) : null}
      </Fact>
    </Facts>
  );
}

/** Asks before a certificate is trusted, with its fingerprint to check (spec 6). */
function Trust({
  asked,
  onDone,
}: {
  asked: CertificateView | null;
  onDone: (added: boolean) => void;
}) {
  const t = useTranslations("certificates");
  const notify = useNotify();
  const add = useAddCertificate();
  return (
    <ConfirmDialog
      open={asked !== null}
      onOpenChange={(open) => {
        if (!open) onDone(false);
      }}
      title={t("trustAsk")}
      confirmLabel={t("trust")}
      busy={add.isPending}
      onConfirm={() => {
        if (asked === null) return;
        add.mutate(asked.pem, {
          onSuccess: () => {
            notify(t("trusted", { subject: asked.subject }));
            onDone(true);
          },
          onError: () => onDone(false),
        });
      }}
    >
      <p className="mb-3">{t("trustBody")}</p>
      {asked ? <Described certificate={asked} /> : null}
      {add.isError ? <ErrorState error={add.error} className="mt-3" /> : null}
    </ConfirmDialog>
  );
}

/** Paste one certificate in PEM. */
function Paste() {
  const t = useTranslations("certificates");
  const notify = useNotify();
  const add = useAddCertificate();
  const [pem, setPem] = useState("");
  const refused = refusalsOf(add.error, ["pem"]);

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate(pem, {
      onSuccess: (added) => {
        notify(t("trusted", { subject: added.subject }));
        setPem("");
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <TextAreaField
        label={t("fields.pem")}
        hint={t("hints.pem")}
        rows={6}
        spellCheck={false}
        className="font-mono text-xs"
        value={pem}
        error={refused.at.pem}
        onChange={(event) => setPem(event.target.value)}
      />
      {add.isError && refused.elsewhere ? <ErrorState error={add.error} /> : null}
      <div>
        <Button type="submit" variant="primary" busy={add.isPending} disabled={pem.trim() === ""}>
          <Plus aria-hidden="true" className="size-4" />
          {t("add")}
        </Button>
      </div>
    </form>
  );
}

/** Ask a host what it presents, and trust one of them once its fingerprint is checked. */
function Fetch() {
  const t = useTranslations("certificates");
  const fetched = useFetchCertificates();
  const [host, setHost] = useState("");
  const [port, setPort] = useState("443");
  const [asked, setAsked] = useState<CertificateView | null>(null);
  const portWrong =
    PORT.test(port) && Number(port) >= 1 && Number(port) <= 65535 ? undefined : t("portRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (host.trim() === "" || portWrong) return;
    fetched.mutate({ host: host.trim(), port: Number(port) });
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-4" noValidate>
        <TextField
          label={t("fields.host")}
          className="min-w-64 flex-1"
          spellCheck={false}
          autoComplete="off"
          value={host}
          onChange={(event) => setHost(event.target.value)}
        />
        <TextField
          label={t("fields.port")}
          className="w-28"
          inputMode="numeric"
          value={port}
          error={portWrong}
          onChange={(event) => setPort(event.target.value)}
        />
        <Button type="submit" busy={fetched.isPending} disabled={host.trim() === ""}>
          <Download aria-hidden="true" className="size-4" />
          {t("fetch")}
        </Button>
      </form>
      {fetched.isError ? <ErrorState error={fetched.error} /> : null}
      {fetched.data ? (
        <ol className="flex flex-col gap-4" aria-label={t("presented")}>
          {fetched.data.chain.map((certificate, index) => (
            <li key={certificate.fingerprint} className="rounded-sm border border-line p-4">
              <p className="label-caps mb-3 text-fg-subtle">
                {index === 0 ? t("own") : t("authority", { number: index })}
              </p>
              <Described certificate={certificate} />
              <Button size="sm" className="mt-3" onClick={() => setAsked(certificate)}>
                {t("trustThis")}
              </Button>
            </li>
          ))}
        </ol>
      ) : null}
      <Trust asked={asked} onDone={() => setAsked(null)} />
    </div>
  );
}

/** Trusted certificates (spec 6, SEC-18): what outbound TLS trusts besides the usual authorities. */
export function CertificatesScreen() {
  const t = useTranslations("certificates");
  const session = useSession();
  const notify = useNotify();
  const page = pageOf(useSearchParams());
  const listed = useCertificates(page);
  const remove = useDeleteCertificate();
  const [removing, setRemoving] = useState<CertificateOut | null>(null);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:certificates:write");
  const pages = listed.data === undefined ? undefined : Math.ceil(listed.data.total / AT_ONCE);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      {mayWrite ? (
        <>
          <Panel className="p-6">
            <h2 className={H2}>{t("fetchTitle")}</h2>
            <p className="mb-4 text-fg-muted">{t("fetchIntro")}</p>
            <Fetch />
          </Panel>
          <Panel className="p-6">
            <h2 className={H2}>{t("pasteTitle")}</h2>
            <Paste />
          </Panel>
        </>
      ) : null}
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
                  <Th>{t("columns.subject")}</Th>
                  <Th>{t("columns.issuer")}</Th>
                  <Th>{t("columns.fingerprint")}</Th>
                  <Th>{t("columns.expires")}</Th>
                  <Th>{t("columns.added")}</Th>
                  {mayWrite ? <Th className="text-right">{t("columns.actions")}</Th> : null}
                </tr>
              </thead>
              <tbody>
                {listed.data.items.map((certificate) => (
                  <tr key={certificate.id} className="hover:bg-raised">
                    <Td className="font-mono text-xs break-all">{certificate.subject}</Td>
                    <Td className="font-mono text-xs break-all text-fg-muted">
                      {certificate.issuer}
                    </Td>
                    <Td
                      className="font-mono text-xs whitespace-nowrap"
                      title={formatFingerprint(certificate.fingerprint)}
                    >
                      {shortFingerprint(certificate.fingerprint)}
                    </Td>
                    <Td className="whitespace-nowrap">
                      <Time value={certificate.not_after} />
                      {expired(certificate) ? (
                        <StatusTag tone="danger" className="ml-2">
                          {t("expired")}
                        </StatusTag>
                      ) : null}
                    </Td>
                    <Td className="text-fg-muted">
                      <span className="block">{certificate.added_by}</span>
                      <Time value={certificate.added_at} />
                    </Td>
                    {mayWrite ? (
                      <Td className="text-right">
                        <Button
                          size="sm"
                          aria-label={t("removeNamed", { subject: certificate.subject })}
                          onClick={() => {
                            remove.reset();
                            setRemoving(certificate);
                          }}
                        >
                          {t("remove")}
                        </Button>
                      </Td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </Table>
            {remove.isError ? <ErrorState error={remove.error} className="m-4" /> : null}
            <Pager
              page={page}
              pages={pages ?? 1}
              hrefFor={(target) => pageHref(CERTIFICATES, target)}
            />
          </>
        )}
      </Panel>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("removeAsk", { subject: removing?.subject ?? "" })}
        confirmLabel={t("remove")}
        busy={remove.isPending}
        onConfirm={() => {
          if (removing === null) return;
          remove.mutate(removing.id, {
            onSuccess: () => notify(t("removed", { subject: removing.subject })),
            onSettled: () => setRemoving(null),
          });
        }}
      >
        {t("removeBody")}
      </ConfirmDialog>
    </div>
  );
}
