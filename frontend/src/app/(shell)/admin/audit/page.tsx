import type { Metadata } from "next";

import { AuditScreen } from "@/screens/audit";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.audit.title };

export default function Page() {
  return <AuditScreen />;
}
