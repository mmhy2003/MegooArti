import type { Metadata } from "next";

import { SelectorsScreen } from "@/screens/content-selectors";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.selectors.title };

export default function Page() {
  return <SelectorsScreen />;
}
