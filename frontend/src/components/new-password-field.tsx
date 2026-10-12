"use client";

import { Dices, Eye, EyeOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { TextField } from "@/components/ui/field";
import { generatePassword } from "@/lib/passwords";

/**
 * A password an administrator sets for someone else (A6): typed, or generated. A
 * generated one is shown, since it has to be told to its owner, and can be copied.
 * The browser is told it is a new password, so that it offers neither to fill in the
 * administrator's own nor to remember this one as theirs.
 */
export function NewPasswordField({
  label,
  hint,
  value,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
}) {
  const t = useTranslations("newPassword");
  const [shown, setShown] = useState(false);
  const Icon = shown ? EyeOff : Eye;
  return (
    <div className="flex flex-col gap-2">
      <TextField
        label={label}
        hint={hint}
        type={shown ? "text" : "password"}
        autoComplete="new-password"
        spellCheck={false}
        value={value}
        error={error}
        onChange={(event) => onChange(event.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          onClick={() => {
            onChange(generatePassword());
            setShown(true);
          }}
        >
          <Dices aria-hidden="true" className="size-4" />
          {t("generate")}
        </Button>
        <Button size="sm" variant="ghost" aria-pressed={shown} onClick={() => setShown(!shown)}>
          <Icon aria-hidden="true" className="size-4" />
          {t("show")}
        </Button>
        {value ? <CopyButton text={value} what={label} /> : null}
      </div>
    </div>
  );
}
