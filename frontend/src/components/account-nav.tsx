"use client";

import { KeyRound, SlidersHorizontal, Ticket, type LucideIcon } from "lucide-react";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { AppLink } from "@/components/ui/link";
import { cn } from "@/lib/cn";
import { ACCOUNT_TOKENS, PREFERENCES } from "@/lib/paths";
import { CHANGE_PASSWORD } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

type Page = { key: "tokens" | "password" | "preferences"; href: Route; icon: LucideIcon };

const PAGES: Page[] = [
  { key: "tokens", href: ACCOUNT_TOKENS, icon: Ticket },
  { key: "password", href: CHANGE_PASSWORD as Route, icon: KeyRound },
  { key: "preferences", href: PREFERENCES, icon: SlidersHorizontal },
];

/**
 * The pages of a person's own account (A1), each a link, with the present one marked.
 * A visitor has no account, and of these pages only the preferences, which are kept in
 * the browser: there is then nothing to choose between, and no list.
 */
export function AccountNav() {
  const t = useTranslations("accountArea");
  const pathname = usePathname();
  const session = useSession();
  if (!session.data?.authenticated) return null;
  return (
    <nav aria-label={t("label")} className="mb-6">
      <ul className="flex flex-wrap gap-2">
        {PAGES.map(({ key, href, icon: Icon }) => {
          const current = pathname === href;
          return (
            <li key={key}>
              <AppLink
                href={href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "label-caps inline-flex min-h-10 items-center gap-2 rounded-sm border px-3",
                  current
                    ? "border-neon-cyan text-ink-cyan"
                    : "border-line-strong text-fg-muted hover:border-neon-cyan hover:text-fg",
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
                {t(`pages.${key}`)}
              </AppLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
