/**
 * The navigation, as data. A screen is put into the navigation by adding an item here,
 * with the permission its API needs: the item is then shown only to those who hold it.
 */
import {
  Boxes,
  HardDrive,
  KeyRound,
  Search,
  Server,
  ShieldCheck,
  Unlock,
  Upload,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { Route } from "next";

import type { SessionInfo } from "@/lib/api/types";
import {
  ANONYMOUS_ACCESS,
  AUTHENTICATION,
  BLOB_STORES,
  MANAGE_REPOSITORIES,
  ROLES,
  SYSTEM,
  USERS,
} from "@/lib/paths";
import { allows, allowsSome } from "@/lib/session/rules";

export type AreaKey = "browse" | "administration";
export type ItemKey =
  | "repositories"
  | "search"
  | "upload"
  | "users"
  | "roles"
  | "anonymousAccess"
  | "authentication"
  | "manageRepositories"
  | "blobStores"
  | "system";

export type NavItem = {
  /** Its name is the message `nav.items.<key>`. */
  key: ItemKey;
  href: Route;
  icon: LucideIcon;
  /** What a caller must hold to be shown it. Without one, everybody is. */
  permission?: string;
  /**
   * Shapes of permission, with `?` for any value: it is shown to whoever holds
   * something that could grant one of them (`repository:?:?:add`).
   */
  anyOf?: string[];
  /** Other addresses that are part of it: the screens it leads to. */
  under?: string[];
};

export type NavArea = {
  /** Its name is the message `nav.areas.<key>`. */
  key: AreaKey;
  items: NavItem[];
};

// Browsing first, then administration (UI-2).
export const NAVIGATION: readonly NavArea[] = [
  {
    key: "browse",
    items: [
      { key: "repositories", href: "/", icon: Boxes, under: ["/browse", "/components"] },
      { key: "search", href: "/search", icon: Search },
      {
        key: "upload",
        href: "/upload",
        icon: Upload,
        // Whoever may add to no repository would find nowhere to upload to.
        anyOf: ["repository:?:?:add", "repository:?:?:edit"],
      },
    ],
  },
  {
    key: "administration",
    items: [
      { key: "users", href: USERS, icon: Users, permission: "admin:users:read" },
      { key: "roles", href: ROLES, icon: ShieldCheck, permission: "admin:roles:read" },
      {
        key: "anonymousAccess",
        href: ANONYMOUS_ACCESS,
        icon: Unlock,
        permission: "admin:settings:read",
      },
      {
        key: "authentication",
        href: AUTHENTICATION,
        icon: KeyRound,
        permission: "admin:security:read",
      },
      {
        key: "manageRepositories",
        href: MANAGE_REPOSITORIES,
        icon: Wrench,
        permission: "admin:repositories:read",
      },
      {
        key: "blobStores",
        href: BLOB_STORES,
        icon: HardDrive,
        permission: "admin:blobstores:read",
      },
      { key: "system", href: SYSTEM, icon: Server, permission: "admin:settings:read" },
    ],
  },
];

/** The areas and items to show this caller. An area with nothing in it is left out. */
export function visible(areas: readonly NavArea[], session: SessionInfo): NavArea[] {
  return areas
    .map((area) => ({
      ...area,
      items: area.items.filter(
        (item) =>
          (item.permission === undefined || allows(session, item.permission)) &&
          (item.anyOf === undefined || item.anyOf.some((shape) => allowsSome(session, shape))),
      ),
    }))
    .filter((area) => area.items.length > 0);
}

/** Whether an item is where the visitor is: its own address, or anything under it. */
export function isCurrent(item: NavItem, pathname: string): boolean {
  const within = (address: string) => pathname === address || pathname.startsWith(`${address}/`);
  if ((item.under ?? []).some(within)) return true;
  return item.href === "/" ? pathname === "/" : within(item.href);
}
