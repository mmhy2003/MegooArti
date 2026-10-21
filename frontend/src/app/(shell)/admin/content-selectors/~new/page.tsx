import type { Metadata } from "next";

import { NewSelectorScreen } from "@/screens/content-selectors";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.selectors.newTitle };

export default function Page() {
  return <NewSelectorScreen />;
}
