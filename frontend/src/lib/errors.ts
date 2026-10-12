"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { isApiError } from "@/lib/api/client";

// The failures the UI has its own words for. Anything else is said as the API said it.
const KNOWN = [
  "network_error",
  "unexpected_answer",
  "forbidden",
  "unauthorized",
  "not_found",
  "internal_error",
] as const;
type Known = (typeof KNOWN)[number];

function isKnown(code: string): code is Known {
  return (KNOWN as readonly string[]).includes(code);
}

/** A function that says, for a person, what went wrong. */
export function useErrorText(): (error: unknown) => string {
  const t = useTranslations("errors");
  return useCallback(
    (error: unknown) => {
      if (!isApiError(error)) return t("fallback");
      if (isKnown(error.code)) return t(error.code);
      return error.message || t("fallback");
    },
    [t],
  );
}
