"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Wordmark } from "@/components/app-shell";
import { ThemeSwitch } from "@/components/theme-switch";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { API_PREFIX, isApiError } from "@/lib/api/client";
import { useSignIn, useSignInSources } from "@/lib/session/session";

// What a sign-in at a provider can come back to this screen with (spec 5).
const PROVIDER_FAULTS = ["denied", "failed", "refused", "expired", "unavailable"] as const;
type ProviderFault = (typeof PROVIDER_FAULTS)[number];

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

/** Why a sign-in at a provider came back here: said once, from the address. */
function ProviderRefusal({ fault, signedIn }: { fault: string | null; signedIn: boolean }) {
  const t = useTranslations("signIn");
  if (fault !== null) {
    const known = (PROVIDER_FAULTS as readonly string[]).includes(fault)
      ? (fault as ProviderFault)
      : "failed";
    return <Alert tone="danger">{t(`provider.${known}`)}</Alert>;
  }
  // Signed in there, and back here: the browser did not keep the session's cookie.
  if (signedIn) {
    return (
      <Alert tone="danger" title={t("cookieNotKeptTitle")}>
        {t("cookieNotKept")}
      </Alert>
    );
  }
  return null;
}

/** "Sign in with …": the sources signed in to at a provider, each a link that leaves for it. */
function Providers({ next }: { next: string }) {
  const t = useTranslations("signIn");
  const found = useSignInSources();
  const listed = found.data?.items ?? [];
  if (listed.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      <p className="label-caps text-center text-fg-subtle">{t("or")}</p>
      {listed.map((source) => (
        <Button key={source.id} asChild>
          <a
            href={`${API_PREFIX}/auth/oidc/${encodeURIComponent(source.id)}/start?next=${encodeURIComponent(next)}`}
          >
            {t("with", { name: source.name })}
          </a>
        </Button>
      ))}
    </div>
  );
}

/**
 * Name and password, or a provider. Once they are accepted the session says who is
 * signed in, and the gate this screen is behind goes on to the screen that was asked for.
 */
export function SignInScreen() {
  const t = useTranslations("signIn");
  const signIn = useSignIn();
  const asked = useSearchParams();
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
          <div className="mb-5 empty:hidden">
            <ProviderRefusal
              fault={signIn.isIdle ? asked.get("error") : null}
              signedIn={signIn.isIdle && asked.get("signed_in") === "1"}
            />
          </div>
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
          <div className="mt-5 empty:hidden">
            <Providers next={asked.get("next") ?? ""} />
          </div>
        </Panel>
      </main>
    </div>
  );
}
