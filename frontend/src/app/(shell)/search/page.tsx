import type { Metadata } from "next";

import { SearchScreen } from "@/screens/search";

import messages from "../../../../messages/en.json";

export const metadata: Metadata = { title: messages.search.title };

export default function Page() {
  return <SearchScreen />;
}
