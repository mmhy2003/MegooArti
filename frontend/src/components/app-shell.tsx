"use client";

import { Menu as MenuIcon, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ThemeSwitch } from "@/components/theme-switch";
import { AppLink } from "@/components/ui/link";
import { UserMenu } from "@/components/user-menu";
import type { SessionInfo } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { isCurrent, NAVIGATION, visible, type NavArea } from "@/lib/navigation";

const MAIN = "main";

/** The wordmark: the name, in the display face, with a neon bar before it. */
export function Wordmark() {
  const t = useTranslations("app");
  return (
    <span className="flex items-center gap-2 font-display text-lg font-bold tracking-[0.12em] text-fg uppercase sm:tracking-[0.2em]">
      <span aria-hidden="true" className="h-5 w-1.5 bg-neon-magenta shadow-glow-sm" />
      {t("name")}
    </span>
  );
}

function Navigation({ areas, onNavigate }: { areas: NavArea[]; onNavigate?: () => void }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-4 lg:flex-row lg:items-center lg:gap-6">
      {areas.map((area) => (
        <li key={area.key} className="flex flex-col gap-1 lg:flex-row lg:items-center lg:gap-2">
          <span className="label-caps text-fg-subtle">{t(`areas.${area.key}`)}</span>
          <ul className="flex flex-col gap-1 lg:flex-row">
            {area.items.map((item) => {
              const current = isCurrent(item, pathname);
              return (
                <li key={item.key}>
                  <AppLink
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={current ? "page" : undefined}
                    className={cn(
                      "label-caps flex min-h-10 items-center gap-2 rounded-sm border px-3",
                      current
                        ? "border-neon-cyan bg-raised text-ink-cyan"
                        : "border-transparent text-fg-muted hover:bg-raised hover:text-fg",
                    )}
                  >
                    <item.icon aria-hidden="true" className="size-4" />
                    {t(`items.${item.key}`)}
                  </AppLink>
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
}

/**
 * What every screen is inside: the header with the navigation, and the content. With
 * `bare`, there is no navigation: for whoever must change their password first.
 */
export function AppShell({
  session,
  bare = false,
  children,
}: {
  session: SessionInfo;
  bare?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("app");
  const [open, setOpen] = useState(false);
  const areas = bare ? [] : visible(NAVIGATION, session);
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href={`#${MAIN}`}
        className="label-caps sr-only z-50 bg-panel px-4 py-3 text-ink-cyan focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {t("skipToContent")}
      </a>
      <header className="border-b border-line-strong bg-panel">
        <div className="mx-auto flex min-h-16 max-w-7xl items-center gap-4 px-4 lg:gap-8">
          <AppLink href="/" className="shrink-0 rounded-sm">
            <Wordmark />
          </AppLink>
          {areas.length > 0 ? (
            <nav aria-label={t("mainNavigation")} className="hidden min-w-0 flex-1 lg:block">
              <Navigation areas={areas} />
            </nav>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            <ThemeSwitch />
            <UserMenu session={session} />
            {areas.length > 0 ? (
              <button
                type="button"
                aria-expanded={open}
                aria-controls="narrow-navigation"
                aria-label={open ? t("closeNavigation") : t("openNavigation")}
                onClick={() => setOpen((was) => !was)}
                className="inline-flex size-10 items-center justify-center rounded-sm border border-line-strong text-fg lg:hidden"
              >
                {open ? (
                  <X aria-hidden="true" className="size-5" />
                ) : (
                  <MenuIcon aria-hidden="true" className="size-5" />
                )}
              </button>
            ) : null}
          </div>
        </div>
        {areas.length > 0 ? (
          <nav
            id="narrow-navigation"
            aria-label={t("mainNavigation")}
            hidden={!open}
            className="border-t border-line px-4 py-4 lg:hidden"
          >
            <Navigation areas={areas} onNavigate={() => setOpen(false)} />
          </nav>
        ) : null}
      </header>
      <main
        id={MAIN}
        tabIndex={-1}
        className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-8 outline-none"
      >
        {children}
      </main>
    </div>
  );
}
