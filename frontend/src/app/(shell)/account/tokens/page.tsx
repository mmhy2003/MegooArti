import type { Metadata } from "next";

import { TokensScreen } from "@/screens/tokens";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.tokens.title };

export default function Page() {
  return <TokensScreen />;
}
