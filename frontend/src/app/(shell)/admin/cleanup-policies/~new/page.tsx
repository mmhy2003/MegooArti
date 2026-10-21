import type { Metadata } from "next";

import { NewPolicyScreen } from "@/screens/cleanup-policies";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.cleanup.newTitle };

export default function Page() {
  return <NewPolicyScreen />;
}
