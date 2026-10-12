import type { Metadata } from "next";

import { SystemScreen } from "@/screens/system";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.system.title };

export default function Page() {
  return <SystemScreen />;
}
