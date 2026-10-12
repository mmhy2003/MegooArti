"use client";

import { useTranslations } from "next-intl";

import { AccountNav } from "@/components/account-nav";
import { useTheme } from "@/components/theme-provider";
import { CheckboxField, ChoiceGroup } from "@/components/ui/inputs";
import { PageHeader, Panel } from "@/components/ui/panel";
import { useSearchKey } from "@/lib/preferences";
import { CHOICES, isChoice } from "@/lib/theme";

/**
 * How this UI behaves for the person in front of it (A11): the mode, and whether `/`
 * goes to the search box. Both are kept in the browser and take effect as they are
 * chosen, so there is nothing to save, and a visitor has them as much as anybody.
 */
export function PreferencesScreen() {
  const t = useTranslations("preferences");
  const mode = useTranslations("theme");
  const { choice, choose } = useTheme();
  const [searchKey, setSearchKey] = useSearchKey();
  return (
    <div className="mx-auto max-w-2xl">
      <AccountNav />
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="flex flex-col gap-8 p-6">
        <ChoiceGroup
          legend={mode("label")}
          value={choice}
          onChange={(value) => {
            if (isChoice(value)) choose(value);
          }}
          options={CHOICES.map((value) => ({ value, label: mode(value) }))}
        />
        <fieldset className="flex min-w-0 flex-col gap-2 border-0 p-0">
          <legend className="label-caps mb-1 p-0 text-fg-muted">{t("keys")}</legend>
          <CheckboxField
            label={t("searchKey")}
            hint={t("searchKeyHint")}
            checked={searchKey}
            onChange={(event) => setSearchKey(event.target.checked)}
          />
        </fieldset>
      </Panel>
    </div>
  );
}
