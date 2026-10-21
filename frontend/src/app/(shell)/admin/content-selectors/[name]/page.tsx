import type { Metadata } from "next";

import { SelectorScreen } from "@/screens/content-selectors";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.selectors.oneTitle };

export default function Page() {
  return <SelectorScreen />;
}
