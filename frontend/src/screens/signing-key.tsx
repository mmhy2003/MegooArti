"use client";

import { Download, KeyRound, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Snippet, Time } from "@/components/ui/details";
import { TextAreaField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useGenerateSigningKey, useImportSigningKey, useSigningKey } from "@/lib/administration";
import type { RepositoryOut, SigningKeyOut } from "@/lib/api/types";
import { refusalsOf } from "@/lib/refusals";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
const H3 = "label-caps mb-3 text-fg-muted";
// What a new OpenPGP key is made with. An apk key is RSA, and is not asked for one.
const ALGORITHMS = ["ed25519", "rsa4096"] as const;
type Algorithm = (typeof ALGORITHMS)[number];

/**
 * The public key as a file to save, under the name a client looks for it by: apk finds
 * a key by its file's name (4.2).
 */
function publicKeyFile(repository: RepositoryOut, key: SigningKeyOut) {
  const rsa = key.kind === "rsa";
  return {
    name: rsa ? `megooarti-${repository.name}.rsa.pub` : `${repository.name}.asc`,
    href: `data:${rsa ? "application/x-pem-file" : "application/pgp-keys"};charset=utf-8,${encodeURIComponent(key.public_key)}`,
  };
}

/**
 * The key a hosted repository or a group of APT, YUM or apk signs its indexes with (4.2):
 * what it is, its public key, and another one for whoever may change the repository.
 * Each change asks first: every machine that uses the repository must then install the
 * new public key (A2).
 */
export function SigningKeyPanel({
  repository,
  mayWrite,
}: {
  repository: RepositoryOut;
  mayWrite: boolean;
}) {
  const t = useTranslations("signing");
  const notify = useNotify();
  const key = useSigningKey(repository.name);
  const generate = useGenerateSigningKey(repository.name);
  const replace = useImportSigningKey(repository.name);
  const openpgp = repository.format !== "apk";
  const [algorithm, setAlgorithm] = useState<Algorithm>("ed25519");
  const [privateKey, setPrivateKey] = useState("");
  const [missing, setMissing] = useState(false);
  const [asking, setAsking] = useState<"generate" | "import" | null>(null);
  const refused = refusalsOf(replace.error, ["private_key"]);
  const name = repository.name;

  function askToImport(event: FormEvent) {
    event.preventDefault();
    replace.reset();
    setMissing(privateKey.trim() === "");
    if (privateKey.trim() !== "") setAsking("import");
  }

  function confirmed() {
    const done = { onSettled: () => setAsking(null) };
    if (asking === "generate") {
      generate.mutate(openpgp ? { algorithm } : {}, {
        ...done,
        onSuccess: () => notify(t("generated", { name })),
      });
    } else {
      replace.mutate(
        { private_key: privateKey },
        {
          ...done,
          onSuccess: () => {
            notify(t("imported", { name }));
            // Kept nowhere once it is the server's: neither here nor in the store.
            setPrivateKey("");
            replace.reset();
          },
        },
      );
    }
  }

  const file = key.data ? publicKeyFile(repository, key.data) : null;
  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("title")}</h2>
      <p className="mb-4 text-fg-muted">{t("intro")}</p>
      {key.isError ? (
        <ErrorState error={key.error} onRetry={() => void key.refetch()} />
      ) : !key.data || !file ? (
        <LoadingState className="p-2" />
      ) : (
        <>
          <Facts className="mb-4">
            <Fact name={t("kind")}>
              {key.data.kind === "openpgp" || key.data.kind === "rsa"
                ? t(`kinds.${key.data.kind}`)
                : key.data.kind}
            </Fact>
            <Fact name={t("algorithm")} mono>
              {key.data.algorithm}
            </Fact>
            <Fact name={t("fingerprint")} copy={key.data.fingerprint} mono>
              {key.data.fingerprint}
            </Fact>
            <Fact name={t("created")}>
              <Time value={key.data.created_at} />
            </Fact>
          </Facts>
          <Snippet label={t("publicKey")} text={key.data.public_key} />
          <div className="mt-3">
            <Button asChild size="sm">
              <a href={file.href} download={file.name}>
                <Download aria-hidden="true" className="size-4" />
                {t("download")}
              </a>
            </Button>
          </div>
        </>
      )}
      {mayWrite ? (
        <div className="mt-6 flex flex-col gap-6 border-t border-line pt-6">
          <div>
            <h3 className={H3}>{t("replaceTitle")}</h3>
            <p className="text-fg-muted">{t("replaceIntro")}</p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            {openpgp ? (
              <SelectField
                label={t("algorithmField")}
                value={algorithm}
                onChange={(event) => setAlgorithm(event.target.value as Algorithm)}
                choices={ALGORITHMS.map((value) => ({
                  value,
                  label: t(`algorithms.${value}`),
                }))}
              />
            ) : null}
            <Button onClick={() => setAsking("generate")}>
              <RefreshCw aria-hidden="true" className="size-4" />
              {t("generate")}
            </Button>
          </div>
          {generate.isError ? <ErrorState error={generate.error} /> : null}
          <form onSubmit={askToImport} className="flex flex-col gap-3" noValidate>
            <TextAreaField
              label={t("privateKey")}
              hint={t(`privateKeyHints.${openpgp ? "openpgp" : "rsa"}`)}
              autoComplete="off"
              value={privateKey}
              error={missing ? t("privateKeyNeeded") : refused.at.private_key}
              onChange={(event) => setPrivateKey(event.target.value)}
            />
            {replace.isError && refused.elsewhere ? <ErrorState error={replace.error} /> : null}
            <div>
              <Button type="submit">
                <KeyRound aria-hidden="true" className="size-4" />
                {t("import")}
              </Button>
            </div>
          </form>
          <ConfirmDialog
            open={asking !== null}
            onOpenChange={(open) => setAsking(open ? asking : null)}
            title={t(asking === "import" ? "importAsk" : "generateAsk", { name })}
            confirmLabel={t(asking === "import" ? "import" : "generate")}
            busy={generate.isPending || replace.isPending}
            onConfirm={confirmed}
          >
            {t("replaceBody", { name })}
          </ConfirmDialog>
        </div>
      ) : null}
    </Panel>
  );
}
