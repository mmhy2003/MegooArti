import type { Metadata } from "next";

import { NewSourceScreen } from "@/screens/source";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.source.newTitle };

export default function Page() {
  return <NewSourceScreen />;
}
