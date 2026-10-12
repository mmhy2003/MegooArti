"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import { HOME } from "@/lib/session/rules";
import { useChangePassword, useSession } from "@/lib/session/session";

// The server's rule, said before the request is made. The server still decides.
const MIN_LENGTH = 8;

type Problems = { current?: string; next?: string; repeat?: string };

/** Which field a refusal by the server is about, by the names it uses for them. */
function fromServer(error: unknown): Problems | null {
  if (!isApiError(error) || error.code !== "validation_error") return null;
  const problems: Problems = {};
  for (const detail of error.details) {
    if (detail.field?.endsWith("current_password")) problems.current = detail.message;
    else problems.next = detail.message;
  }
  return problems.current || problems.next ? problems : null;
}

/**
 * Changing one's own password. It is also the only screen of a user whose password was
 * set for them, until they have chosen their own.
 */
export function ChangePasswordScreen() {
  const t = useTranslations("password");
  const session = useSession();
  const change = useChangePassword();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [problems, setProblems] = useState<Problems>({});
  // Asked once, when the screen opens: after the change it is no longer true, and the
  // gate has by then gone on to another screen.
  const [forced] = useState(session.data?.must_change_password ?? false);

  function check(): Problems {
    if (next.length < MIN_LENGTH) return { next: t("tooShort", { min: MIN_LENGTH }) };
    if (next === current) return { next: t("notDifferent") };
    if (next !== repeat) return { repeat: t("notTheSame") };
    return {};
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const found = check();
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setRepeat("");
          // Whoever was made to come here goes on to where they were going.
          if (forced) router.replace(HOME);
        },
        onError: (error) => setProblems(fromServer(error) ?? {}),
      },
    );
  }

  const unexplained = change.isError && fromServer(change.error) === null;
  return (
    <div className="mx-auto max-w-lg">
      <PageHeader title={forced ? t("mustChangeTitle") : t("title")} />
      {forced ? (
        <Alert tone="warning" className="mb-6">
          {t("mustChange")}
        </Alert>
      ) : null}
      <Panel className="p-6">
        <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
          <TextField
            label={t("current")}
            name="current-password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            error={problems.current}
            onChange={(event) => setCurrent(event.target.value)}
          />
          <TextField
            label={t("new")}
            name="new-password"
            type="password"
            autoComplete="new-password"
            required
            value={next}
            hint={t("newHint", { min: MIN_LENGTH })}
            error={problems.next}
            onChange={(event) => setNext(event.target.value)}
          />
          <TextField
            label={t("repeat")}
            name="repeat-password"
            type="password"
            autoComplete="new-password"
            required
            value={repeat}
            error={problems.repeat}
            onChange={(event) => setRepeat(event.target.value)}
          />
          {unexplained ? <ErrorState error={change.error} /> : null}
          {change.isSuccess ? <Alert tone="success">{t("changed")}</Alert> : null}
          <Button
            type="submit"
            variant="primary"
            busy={change.isPending}
            disabled={current === "" || next === "" || repeat === ""}
          >
            {t("submit")}
          </Button>
        </form>
      </Panel>
    </div>
  );
}
