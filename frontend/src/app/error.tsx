"use client";

import { RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/** A screen threw while it was being drawn. The rest of the UI is still there. */
export default function ScreenError({ reset }: { error: Error; reset: () => void }) {
  const t = useTranslations("crash");
  return (
    <div className="mx-auto flex min-h-dvh max-w-xl items-center px-4">
      <Alert tone="danger" title={t("title")} className="w-full">
        <p>{t("body")}</p>
        <Button size="sm" className="mt-3" onClick={reset}>
          <RotateCw aria-hidden="true" className="size-4" />
          {t("reload")}
        </Button>
      </Alert>
    </div>
  );
}
