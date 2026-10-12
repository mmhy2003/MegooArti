/**
 * The navigation, as data. A screen is put into the navigation by adding an item here,
 * with the permission its API needs: the item is then shown only to those who hold it.
 */
import { Boxes, type LucideIcon } from "lucide-react";
import type { Route } from "next";

import type { SessionInfo } from "@/lib/api/types";
import { allows } from "@/lib/session/rules";

export type AreaKey = "browse" | "administration";
export type ItemKey = "repositories";

export type NavItem = {
  /** Its name is the message `nav.items.<key>`. */
  key: ItemKey;
  href: Route;
  icon: LucideIcon;
  /** What a caller must hold to be shown it. Without one, everybody is. */
  permission?: string;
};

export type NavArea = {
  /** Its name is the message `nav.areas.<key>`. */
  key: AreaKey;
  items: NavItem[];
};

// Browsing first, then administration (UI-2). Plan 10 adds its screens to both.
export const NAVIGATION: readonly NavArea[] = [
  { key: "browse", items: [{ key: "repositories", href: "/", icon: Boxes }] },
  { key: "administration", items: [] },
];

/** The areas and items to show this caller. An area with nothing in it is left out. */
export function visible(areas: readonly NavArea[], session: SessionInfo): NavArea[] {
  return areas
    .map((area) => ({
      ...area,
      items: area.items.filter(
        (item) => item.permission === undefined || allows(session, item.permission),
      ),
    }))
    .filter((area) => area.items.length > 0);
}

/** Whether an item is where the visitor is: its own address, or anything under it. */
export function isCurrent(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
