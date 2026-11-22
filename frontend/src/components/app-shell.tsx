"use client";

import { Menu as MenuIcon, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { Dialog, Tooltip } from "radix-ui";
import { useEffect, useState, type ReactNode } from "react";

import { SearchBox } from "@/components/search-box";
import { ThemeSwitch } from "@/components/theme-switch";
import { AppLink } from "@/components/ui/link";
import { UserMenu } from "@/components/user-menu";
import type { SessionInfo } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { isCurrent, NAVIGATION, visible, type NavArea } from "@/lib/navigation";
import { useSidebarRail } from "@/lib/use-sidebar";

const MAIN = "main";
/** Wide enough for the sidebar: Tailwind's `lg`. */
const WIDE = "(min-width: 1024px)";

/**
 * The wordmark: the name, in the display face, with a neon bar before it. With
 * `collapsible`, the rail shows the bar alone, and the name is still read out.
 */
export function Wordmark({ collapsible = false }: { collapsible?: boolean }) {
  const t = useTranslations("app");
  return (
    <span className="flex items-center gap-2 font-display text-lg font-bold tracking-[0.08em] text-fg uppercase">
      <span aria-hidden="true" className="h-5 w-1.5 bg-neon-cyan shadow-glow-sm" />
      <span className={cn(collapsible && "rail:sr-only")}>{t("name")}</span>
    </span>
  );
}

/**
 * The areas and their links. With `collapsible`, it is the sidebar's: in the rail only
 * the icons are seen, each link keeps its name for a screen reader, and shows it beside
 * it on hover or focus.
 */
function Navigation({
  areas,
  onNavigate,
  collapsible = false,
  rail = false,
}: {
  areas: NavArea[];
  onNavigate?: () => void;
  collapsible?: boolean;
  rail?: boolean;
}) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-4">
      {areas.map((area) => (
        <li key={area.key} className="flex flex-col gap-1">
          <span className={cn("label-caps px-3 text-fg-muted", collapsible && "rail:sr-only")}>
            {t(`areas.${area.key}`)}
          </span>
          {collapsible ? (
            <span aria-hidden="true" className="mx-3 hidden h-px bg-line rail:block" />
          ) : null}
          <ul className="flex flex-col gap-1">
            {area.items.map((item) => {
              const current = isCurrent(item, pathname);
              const name = t(`items.${item.key}`);
              const link = (
                <AppLink
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "flex min-h-10 items-center gap-2 rounded-sm border px-3 text-sm font-medium",
                    current
                      ? "border-neon-cyan bg-raised text-ink-cyan"
                      : "border-transparent text-fg-muted hover:bg-raised hover:text-fg",
                  )}
                >
                  <item.icon aria-hidden="true" className="size-4 shrink-0" />
                  <span className={cn(collapsible && "rail:sr-only")}>{name}</span>
                </AppLink>
              );
              return (
                <li key={item.key}>
                  {collapsible ? (
                    // The same tree open or a rail: only the rail lets the tip show.
                    <Tooltip.Root open={rail ? undefined : false}>
                      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content
                          side="right"
                          sideOffset={8}
                          className="bevel z-50 border border-line-strong bg-panel px-2 py-1 text-sm text-fg shadow-lift"
                        >
                          {name}
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>
                  ) : (
                    link
                  )}
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
 * What every screen is inside: the sidebar with the navigation, and beside it the
 * header and the content. With `bare`, there is no navigation: for whoever must change
 * their password first.
 *
 * In a wide window the sidebar can be collapsed to a rail of icons, a choice kept in
 * the browser (lib/sidebar.ts). Its list scrolls by itself, so an administrator's many
 * items never run under the header. Below that width the navigation is a drawer, a
 * modal dialog opened from the header's menu button.
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
  const [rail, setRail] = useSidebarRail();
  const areas = bare ? [] : visible(NAVIGATION, session);
  // Where the sidebar is shown, the drawer has no reason to stay open.
  useEffect(() => {
    const wide = window.matchMedia(WIDE);
    const close = (event: MediaQueryListEvent) => {
      if (event.matches) setOpen(false);
    };
    wide.addEventListener("change", close);
    return () => wide.removeEventListener("change", close);
  }, []);
  return (
    <Tooltip.Provider delayDuration={300}>
      <div className="flex min-h-dvh">
        <a
          href={`#${MAIN}`}
          className="label-caps sr-only z-50 bg-panel px-4 py-3 text-ink-cyan focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          {t("skipToContent")}
        </a>
        {areas.length > 0 ? (
          <div
            id="sidebar"
            className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-panel transition-[width] lg:flex rail:w-16"
          >
            <AppLink href="/" className="flex min-h-16 items-center rounded-sm px-4">
              <Wordmark collapsible />
            </AppLink>
            <nav
              aria-label={t("mainNavigation")}
              className="min-h-0 flex-1 overflow-y-auto px-2 py-4"
            >
              <Navigation areas={areas} collapsible rail={rail} />
            </nav>
            <button
              type="button"
              aria-controls="sidebar"
              aria-expanded={!rail}
              aria-label={rail ? t("expandNavigation") : t("collapseNavigation")}
              onClick={() => setRail(!rail)}
              className="m-2 inline-flex min-h-10 items-center justify-center gap-2 rounded-sm border border-line-strong text-fg-muted hover:border-neon-cyan hover:text-fg"
            >
              {rail ? (
                <PanelLeftOpen aria-hidden="true" className="size-4" />
              ) : (
                <PanelLeftClose aria-hidden="true" className="size-4" />
              )}
            </button>
          </div>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* Sticky is positioned too: the sign-out alert still sits under the header. */}
          <header className="sticky top-0 z-30 border-b border-line-strong bg-panel">
            <div className="mx-auto flex min-h-16 max-w-7xl items-center gap-4 px-4">
              <AppLink
                href="/"
                className={cn("shrink-0 rounded-sm", areas.length > 0 && "lg:hidden")}
              >
                <Wordmark />
              </AppLink>
              <div className="ml-auto flex items-center gap-2">
                {bare ? null : <SearchBox className="hidden w-56 md:block lg:w-80" />}
                <ThemeSwitch bare={bare} />
                <UserMenu session={session} />
                {areas.length > 0 ? (
                  <Dialog.Root open={open} onOpenChange={setOpen}>
                    <Dialog.Trigger asChild>
                      <button
                        type="button"
                        aria-label={t("openNavigation")}
                        className="inline-flex size-10 items-center justify-center rounded-sm border border-line-strong text-fg lg:hidden"
                      >
                        <MenuIcon aria-hidden="true" className="size-5" />
                      </button>
                    </Dialog.Trigger>
                    <Dialog.Portal>
                      <Dialog.Overlay
                        data-drawer-scrim=""
                        className="fixed inset-0 z-40 bg-page/80 lg:hidden"
                      />
                      <Dialog.Content
                        id="narrow-navigation"
                        aria-describedby={undefined}
                        className="fixed inset-y-0 left-0 z-50 flex w-[min(20rem,85vw)] flex-col gap-4 overflow-y-auto border-r border-line-strong bg-panel p-4 shadow-lift lg:hidden"
                      >
                        <Dialog.Title className="sr-only">{t("mainNavigation")}</Dialog.Title>
                        <div className="flex items-center justify-between gap-2">
                          <Wordmark />
                          <Dialog.Close asChild>
                            <button
                              type="button"
                              aria-label={t("closeNavigation")}
                              className="inline-flex size-10 items-center justify-center rounded-sm border border-line-strong text-fg"
                            >
                              <X aria-hidden="true" className="size-5" />
                            </button>
                          </Dialog.Close>
                        </div>
                        <SearchBox className="md:hidden" />
                        <nav aria-label={t("mainNavigation")}>
                          <Navigation areas={areas} onNavigate={() => setOpen(false)} />
                        </nav>
                      </Dialog.Content>
                    </Dialog.Portal>
                  </Dialog.Root>
                ) : null}
              </div>
            </div>
          </header>
          <main
            id={MAIN}
            tabIndex={-1}
            className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-8 outline-none"
          >
            {children}
          </main>
        </div>
      </div>
    </Tooltip.Provider>
  );
}
