"use client";

import { KeyRound, LogIn, LogOut, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { AppLink } from "@/components/ui/link";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import type { SessionInfo } from "@/lib/api/types";
import { CHANGE_PASSWORD, SIGN_IN } from "@/lib/session/rules";
import { useSignOut } from "@/lib/session/session";

/** Who is signed in, and what they can do about it. For a visitor, the way to sign in. */
export function UserMenu({ session }: { session: SessionInfo }) {
  const t = useTranslations("account");
  const router = useRouter();
  const signOut = useSignOut();

  if (session.user === null) {
    return (
      <Button asChild variant="primary" size="sm">
        <AppLink href={SIGN_IN}>
          <LogIn aria-hidden="true" className="size-4" />
          {t("signIn")}
        </AppLink>
      </Button>
    );
  }

  const name = session.user.display_name || session.user.username;
  return (
    <Menu>
      <MenuTrigger
        aria-label={t("menu", { name })}
        className="inline-flex min-h-10 max-w-48 items-center gap-2 rounded-sm border border-line-strong px-3 text-sm text-fg hover:border-neon-cyan"
      >
        <UserRound aria-hidden="true" className="size-4 shrink-0 text-neon-magenta" />
        {/* On a narrow screen the icon stands for it: the button is still named. */}
        <span className="hidden truncate sm:inline">{name}</span>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{t("signedInAs")}</MenuLabel>
        <p className="px-3 pb-2 font-mono text-sm break-all text-fg">{session.user.username}</p>
        <MenuSeparator />
        {session.must_change_password ? null : (
          <MenuItem onSelect={() => router.push(CHANGE_PASSWORD)}>
            <KeyRound aria-hidden="true" className="size-4" />
            {t("changePassword")}
          </MenuItem>
        )}
        <MenuItem disabled={signOut.isPending} onSelect={() => signOut.mutate()}>
          <LogOut aria-hidden="true" className="size-4" />
          {t("signOut")}
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
