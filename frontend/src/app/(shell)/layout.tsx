import type { ReactNode } from "react";

import { SessionGate } from "@/components/session-gate";

export default function ShellLayout({ children }: { children: ReactNode }) {
  return <SessionGate shell>{children}</SessionGate>;
}
