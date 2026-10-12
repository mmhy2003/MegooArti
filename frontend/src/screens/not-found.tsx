"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { AppLink } from "@/components/ui/link";
import { EmptyState } from "@/components/ui/states";

/** What a screen of the shell shows at an address that is nothing's. */
export function NothingHere() {
  const t = useTranslations("notFound");
  return (
    <EmptyState
      page
      title={t("title")}
      action={
        <Button asChild variant="primary">
          <AppLink href="/">{t("home")}</AppLink>
        </Button>
      }
    >
      {t("body")}
    </EmptyState>
  );
}

/** The whole page for an address no route answers: it has no shell around it. */
export function NotFoundScreen() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <NothingHere />
    </main>
  );
}
