"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { AppLink } from "@/components/ui/link";
import { EmptyState } from "@/components/ui/states";

export function NotFoundScreen() {
  const t = useTranslations("notFound");
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <EmptyState
        title={t("title")}
        action={
          <Button asChild variant="primary">
            <AppLink href="/">{t("home")}</AppLink>
          </Button>
        }
      >
        {t("body")}
      </EmptyState>
    </main>
  );
}
