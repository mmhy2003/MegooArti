import type { Metadata } from "next";

import { PoliciesScreen } from "@/screens/cleanup-policies";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.cleanup.title };

export default function Page() {
  return <PoliciesScreen />;
}
