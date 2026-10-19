import type { Metadata } from "next";

import { SourceScreen } from "@/screens/source";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.source.oneTitle };

export default function Page() {
  return <SourceScreen />;
}
