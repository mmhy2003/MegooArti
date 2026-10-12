"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Wordmark } from "@/components/app-shell";
import { ThemeSwitch } from "@/components/theme-switch";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import { useSignIn } from "@/lib/session/session";

/** Why signing in did not work, where the screen has its own words for it. */
function Refusal({ error }: { error: unknown }) {
  const t = useTranslations("signIn");
  if (isApiError(error)) {
    if (error.code === "cookie_not_kept") {
      return (
        <Alert tone="danger" title={t("cookieNotKeptTitle")}>
          {t("cookieNotKept")}
        </Alert>
      );
    }
    if (error.status === 401) return <Alert tone="danger">{t("wrong")}</Alert>;
    if (error.status === 429) return <Alert tone="warning">{t("tooManyAttempts")}</Alert>;
  }
  return <ErrorState error={error} />;
}

/**
 * Name and password. Once they are accepted the session says who is signed in, and
 * the gate this screen is behind goes on to the screen that was asked for.
 */
export function SignInScreen() {
  const t = useTranslations("signIn");
  const signIn = useSignIn();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    signIn.mutate({ username, password });
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="flex justify-end p-4">
        <ThemeSwitch />
      </div>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 px-4 pb-24">
        <Wordmark />
        <Panel className="p-6 shadow-glow-sm">
          <h1 className="mb-6 text-xl font-semibold text-fg uppercase">{t("title")}</h1>
          <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
            <TextField
              label={t("username")}
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <TextField
              label={t("password")}
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {signIn.isError ? <Refusal error={signIn.error} /> : null}
            <Button
              type="submit"
              variant="primary"
              busy={signIn.isPending}
              disabled={username === "" || password === ""}
            >
              {t("submit")}
            </Button>
          </form>
        </Panel>
      </main>
    </div>
  );
}
