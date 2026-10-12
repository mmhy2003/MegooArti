"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { decide } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

function Waiting() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <LoadingState />
    </div>
  );
}

function Gate({ shell, children }: { shell: boolean; children: ReactNode }) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const query = search.toString();
  const path = query ? `${pathname}?${query}` : pathname;
  const decision = session.data ? decide(session.data, path, search.get("next")) : null;
  const goTo = decision !== null && !decision.show ? decision.goTo : null;

  useEffect(() => {
    // `goTo` is one of our own addresses: `decide` makes it from the rules.
    if (goTo !== null) router.replace(goTo as Route);
  }, [goTo, router]);

  if (session.isError) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-xl items-center px-4">
        <ErrorState
          error={session.error}
          onRetry={() => void session.refetch()}
          className="w-full"
        />
      </div>
    );
  }
  if (!session.data || goTo !== null) return <Waiting />;
  if (!shell) return children;
  return (
    <AppShell session={session.data} bare={session.data.must_change_password}>
      {children}
    </AppShell>
  );
}

/**
 * Stands before every screen: asks who is signed in, and shows the screen, or goes to
 * the one this visitor should see instead (the design's section 7).
 */
export function SessionGate({ shell, children }: { shell: boolean; children: ReactNode }) {
  return (
    // The address's query is only known in the browser.
    <Suspense fallback={<Waiting />}>
      <Gate shell={shell}>{children}</Gate>
    </Suspense>
  );
}
