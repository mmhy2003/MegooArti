import type { Metadata } from "next";

import { PolicyScreen } from "@/screens/cleanup-policies";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.cleanup.oneTitle };

export default function Page() {
  return <PolicyScreen />;
}
