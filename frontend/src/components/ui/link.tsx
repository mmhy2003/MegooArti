import NextLink from "next/link";
import type { ComponentProps } from "react";

/**
 * A link within the UI. Next.js would fetch what a link leads to as soon as it is on
 * the screen. Here nothing is fetched until it is followed: a screen is a shell, its
 * data comes from the API, and a visitor who is not signed in should cause no requests
 * for screens they have not asked for.
 */
export function AppLink(props: ComponentProps<typeof NextLink>) {
  return <NextLink prefetch={false} {...props} />;
}
