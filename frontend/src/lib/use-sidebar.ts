"use client";

import { useCallback, useSyncExternalStore } from "react";

import { setSidebarRail, sidebarIsRail, subscribe } from "@/lib/sidebar";

/** Whether the sidebar is a rail, and a way to say so. On the server it is open. */
export function useSidebarRail(): [boolean, (rail: boolean) => void] {
  const rail = useSyncExternalStore(subscribe, sidebarIsRail, () => false);
  return [rail, useCallback((next: boolean) => setSidebarRail(next), [])];
}
