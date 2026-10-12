"use client";

import { Monitor, Moon, SlidersHorizontal, Sun, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { useTheme } from "@/components/theme-provider";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { PREFERENCES } from "@/lib/paths";
import { CHOICES, isChoice, type ThemeChoice } from "@/lib/theme";

const ICONS: Record<ThemeChoice, LucideIcon> = { light: Sun, dark: Moon, system: Monitor };

/**
 * Light, dark, or as the system says (UI-10). It also leads to the other preferences
 * (A11): it is in the header for everybody, a visitor too, and so is the one way there
 * that everybody has. `bare` leaves that out, where no other screen can be reached.
 */
export function ThemeSwitch({ bare = false }: { bare?: boolean }) {
  const t = useTranslations("theme");
  const router = useRouter();
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
        {bare ? null : (
          <>
            <MenuSeparator />
            <MenuItem onSelect={() => router.push(PREFERENCES)}>
              <SlidersHorizontal aria-hidden="true" className="size-4" />
              {t("more")}
            </MenuItem>
          </>
        )}
      </MenuContent>
    </Menu>
  );
}
