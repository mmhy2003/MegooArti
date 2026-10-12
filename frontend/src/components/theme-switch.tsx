"use client";

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { useTheme } from "@/components/theme-provider";
import {
  Menu,
  MenuContent,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuTrigger,
} from "@/components/ui/menu";
import { CHOICES, isChoice, type ThemeChoice } from "@/lib/theme";

const ICONS: Record<ThemeChoice, LucideIcon> = { light: Sun, dark: Moon, system: Monitor };

/** Light, dark, or as the system says (UI-10). */
export function ThemeSwitch() {
  const t = useTranslations("theme");
  const { choice, choose } = useTheme();
  const Current = ICONS[choice];
  return (
    <Menu>
      <MenuTrigger
        aria-label={t("current", { choice: t(choice) })}
        className="inline-flex size-10 items-center justify-center rounded-sm border border-transparent text-fg-muted hover:border-neon-cyan hover:text-ink-cyan"
      >
        <Current aria-hidden="true" className="size-5" />
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{t("label")}</MenuLabel>
        <MenuRadioGroup
          value={choice}
          onValueChange={(value) => {
            if (isChoice(value)) choose(value);
          }}
        >
          {CHOICES.map((option) => {
            const Icon = ICONS[option];
            return (
              <MenuRadioItem key={option} value={option}>
                <Icon aria-hidden="true" className="size-4" />
                {t(option)}
              </MenuRadioItem>
            );
          })}
        </MenuRadioGroup>
      </MenuContent>
    </Menu>
  );
}
